from hashlib import sha256
import time
import uuid

import pytest

from libp2p.pubsub.segmentation import (
    DEFAULT_SEGMENT_SIZE,
    DEFAULT_MAX_MESSAGE_SIZE,
    MAX_BUFFERED_MESSAGE_IDS,
    ReassemblyBuffer,
    reassemble_segments,
    segment_message,
    should_segment,
)
from libp2p.pubsub.pb import rpc_pb2


class TestShouldSegment:
    def test_below_threshold(self):
        assert should_segment(512 * 1024) is False
        assert should_segment(DEFAULT_MAX_MESSAGE_SIZE - 1) is False
        assert should_segment(DEFAULT_MAX_MESSAGE_SIZE) is False  # equal = don't segment

    def test_above_threshold(self):
        assert should_segment(DEFAULT_MAX_MESSAGE_SIZE + 1) is True
        assert should_segment(2 * 1024 * 1024) is True

    def test_custom_threshold(self):
        assert should_segment(1000, threshold=500) is True
        assert should_segment(100, threshold=500) is False


class TestSegmentMessage:
    def test_small_data_single_segment(self):
        data = b"hello world"
        mid = b"\x01" * 8
        segs = segment_message(mid, data, segment_size=4096)
        assert len(segs) == 1
        assert segs[0].segmentIndex == 0
        assert segs[0].totalSegments == 1
        assert segs[0].payload == data
        assert segs[0].checksum == sha256(data).digest()

    def test_large_data_multiple_segments(self):
        data = b"x" * 100_000
        mid = uuid.uuid4().bytes
        seg_size = 30_000
        segs = segment_message(mid, data, segment_size=seg_size)
        expected_count = (len(data) + seg_size - 1) // seg_size
        assert len(segs) == expected_count

        # Verify each segment
        for i, seg in enumerate(segs):
            assert seg.messageID == mid
            assert seg.segmentIndex == i
            assert seg.totalSegments == expected_count
            expected_payload = data[i * seg_size : (i + 1) * seg_size]
            assert seg.payload == expected_payload

        # Verify checksums match across all segments
        for seg in segs:
            assert seg.checksum == sha256(data).digest()

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="cannot segment empty data"):
            segment_message(b"\x00", b"", segment_size=1024)

    def test_message_id_preserved(self):
        data = b"a" * 50_000
        mid = b"\xde\xad\xbe\xef"
        segs = segment_message(mid, data, segment_size=20_000)
        for seg in segs:
            assert seg.messageID == mid


class TestReassembleSegments:
    def test_reassemble_single_segment(self):
        data = b"hello world"
        mid = b"\x01" * 8
        segs = segment_message(mid, data)
        result = reassemble_segments(segs)
        assert result == data

    def test_reassemble_multiple_segments(self):
        data = b"x" * 100_000
        mid = uuid.uuid4().bytes
        segs = segment_message(mid, data, segment_size=30_000)
        result = reassemble_segments(segs)
        assert result == data

    def test_reassemble_out_of_order(self):
        data = b"abcdefghijklmnopqrstuvwxyz" * 1000
        mid = b"\x02" * 8
        segs = segment_message(mid, data, segment_size=5000)
        # Reverse the order
        segs.reverse()
        result = reassemble_segments(segs)
        assert result == data

    def test_checksum_mismatch_raises(self):
        data = b"original data"
        mid = b"\x03" * 8
        segs = segment_message(mid, data, segment_size=1024)
        # Tamper with the first segment's payload
        segs[0].payload = b"tampered"
        with pytest.raises(ValueError, match="checksum mismatch"):
            reassemble_segments(segs)

    def test_no_checksum_no_verification(self):
        seg = rpc_pb2.LargeMessageSegmentationExtension(
            messageID=b"\x04" * 8,
            segmentIndex=0,
            totalSegments=1,
            payload=b"hello",
            # no checksum set
        )
        result = reassemble_segments([seg])
        assert result == b"hello"

    def test_empty_segments_raises(self):
        with pytest.raises(ValueError, match="no segments to reassemble"):
            reassemble_segments([])


class TestReassemblyBuffer:
    def test_single_segment_completes_immediately(self):
        buf = ReassemblyBuffer(timeout=60)
        data = b"hello world"
        mid = b"\x10" * 8
        segs = segment_message(mid, data, segment_size=4096)
        result = buf.add_segment(segs[0])
        assert result == data
        assert buf.pending_count() == 0

    def test_multiple_segments_out_of_order(self):
        buf = ReassemblyBuffer(timeout=60)
        data = b"x" * 100_000
        mid = uuid.uuid4().bytes
        segs = segment_message(mid, data, segment_size=30_000)
        # Feed in reverse order
        for seg in reversed(segs):
            result = buf.add_segment(seg)
            if result is not None:
                assert result == data
        assert buf.pending_count() == 0

    def test_partial_set_returns_none(self):
        buf = ReassemblyBuffer(timeout=60)
        data = b"x" * 100_000
        mid = uuid.uuid4().bytes
        segs = segment_message(mid, data, segment_size=30_000)
        # Only add first two segments
        result = buf.add_segment(segs[0])
        assert result is None
        result = buf.add_segment(segs[1])
        assert result is None
        assert buf.pending_count() == 1
        assert buf.has_pending(mid)

    def test_timeout_eviction(self):
        buf = ReassemblyBuffer(timeout=0.01)  # very short timeout
        data = b"x" * 100_000
        mid = uuid.uuid4().bytes
        segs = segment_message(mid, data, segment_size=50_000)
        buf.add_segment(segs[0])
        assert buf.pending_count() == 1
        time.sleep(0.02)
        evicted = buf.garbage_collect()
        assert evicted == 1
        assert buf.pending_count() == 0

    def test_max_cap_evicts_oldest(self):
        buf = ReassemblyBuffer(timeout=300, max_pending=3)
        # Fill with 3 incomplete sets
        for i in range(3):
            mid = bytes([i] * 8)
            seg = rpc_pb2.LargeMessageSegmentationExtension(
                messageID=mid,
                segmentIndex=0,
                totalSegments=2,
                payload=b"a",
            )
            buf.add_segment(seg)
        assert buf.pending_count() == 3
        # Adding a 4th should evict the oldest
        mid4 = b"\x04" * 8
        seg4 = rpc_pb2.LargeMessageSegmentationExtension(
            messageID=mid4,
            segmentIndex=0,
            totalSegments=2,
            payload=b"b",
        )
        buf.add_segment(seg4)
        assert buf.pending_count() == 3
        assert buf.has_pending(mid4)
        assert not buf.has_pending(b"\x00" * 8)  # oldest evicted

    def test_protocol_violation_total_changed(self):
        buf = ReassemblyBuffer(timeout=60)
        mid = b"\xff" * 8
        seg1 = rpc_pb2.LargeMessageSegmentationExtension(
            messageID=mid,
            segmentIndex=0,
            totalSegments=3,
            payload=b"a",
        )
        seg2 = rpc_pb2.LargeMessageSegmentationExtension(
            messageID=mid,
            segmentIndex=0,
            totalSegments=5,  # different total!
            payload=b"b",
        )
        buf.add_segment(seg1)
        result = buf.add_segment(seg2)
        assert result is None  # discarded
        assert not buf.has_pending(mid)

    def test_on_complete_callback(self):
        callback_called = []
        buf = ReassemblyBuffer(timeout=60, on_complete=lambda data: callback_called.append(data))
        data = b"callback test data"
        mid = b"\xaa" * 8
        segs = segment_message(mid, data, segment_size=4096)
        buf.add_segment(segs[0])
        assert len(callback_called) == 1
        assert callback_called[0] == data

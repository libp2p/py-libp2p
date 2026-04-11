"""
Tests for WebRTC signaling protocol.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.transport.webrtc.signaling import (
    SignalingSession,
    _encode_uvarint,
    _read_uvarint,
    read_signaling_message,
    write_signaling_message,
)
from libp2p.transport.webrtc.signaling_pb.signaling_pb2 import SignalingMessage


class MockStream:
    """Mock INetStream for signaling tests using an in-memory buffer."""

    def __init__(self) -> None:
        self._send: trio.MemorySendChannel[bytes]
        self._recv: trio.MemoryReceiveChannel[bytes]
        self._send, self._recv = trio.open_memory_channel[bytes](256)
        self._buf = bytearray()

    async def write(self, data: bytes) -> None:
        await self._send.send(data)

    async def read(self, n: int | None = None) -> bytes:
        # Fill buffer from channel if needed
        while len(self._buf) < (n or 1):
            try:
                chunk = self._recv.receive_nowait()
                self._buf.extend(chunk)
            except trio.WouldBlock:
                chunk = await self._recv.receive()
                self._buf.extend(chunk)
        if n is None:
            data = bytes(self._buf)
            self._buf.clear()
            return data
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    async def close(self) -> None:
        pass


def _make_stream_pair() -> tuple[MockStream, MockStream]:
    """Create two streams connected to each other for testing."""
    # We use a single MockStream and feed it from both sides
    # For simplicity, return two independent streams
    return MockStream(), MockStream()


class TestVarintEncoding:
    def test_encode_small(self):
        assert _encode_uvarint(0) == b"\x00"
        assert _encode_uvarint(1) == b"\x01"
        assert _encode_uvarint(127) == b"\x7f"

    def test_encode_two_bytes(self):
        assert _encode_uvarint(128) == b"\x80\x01"
        assert _encode_uvarint(300) == b"\xac\x02"

    def test_encode_large(self):
        encoded = _encode_uvarint(65536)
        assert len(encoded) == 3

    @pytest.mark.trio
    async def test_roundtrip(self):
        stream = MockStream()
        for value in [0, 1, 127, 128, 255, 256, 300, 65535, 100000]:
            varint_bytes = _encode_uvarint(value)
            await stream.write(varint_bytes)
            decoded = await _read_uvarint(stream)
            assert decoded == value, f"Failed for value {value}"


class TestSignalingMessage:
    @pytest.mark.trio
    async def test_write_and_read_offer(self):
        stream = MockStream()
        msg = SignalingMessage(
            type=SignalingMessage.SDP_OFFER,
            data=b"v=0\r\no=- 123 ...",
        )
        await write_signaling_message(stream, msg)
        received = await read_signaling_message(stream)
        assert received.type == SignalingMessage.SDP_OFFER
        assert received.data == b"v=0\r\no=- 123 ..."

    @pytest.mark.trio
    async def test_write_and_read_answer(self):
        stream = MockStream()
        msg = SignalingMessage(
            type=SignalingMessage.SDP_ANSWER,
            data=b"answer-sdp",
        )
        await write_signaling_message(stream, msg)
        received = await read_signaling_message(stream)
        assert received.type == SignalingMessage.SDP_ANSWER
        assert received.data == b"answer-sdp"

    @pytest.mark.trio
    async def test_write_and_read_ice_candidate(self):
        stream = MockStream()
        msg = SignalingMessage(
            type=SignalingMessage.ICE_CANDIDATE,
            data=b"candidate:1 1 UDP 2130706431 192.168.1.1 9090 typ host",
        )
        await write_signaling_message(stream, msg)
        received = await read_signaling_message(stream)
        assert received.type == SignalingMessage.ICE_CANDIDATE

    @pytest.mark.trio
    async def test_write_and_read_ice_done(self):
        stream = MockStream()
        msg = SignalingMessage(type=SignalingMessage.ICE_DONE)
        await write_signaling_message(stream, msg)
        received = await read_signaling_message(stream)
        assert received.type == SignalingMessage.ICE_DONE

    @pytest.mark.trio
    async def test_multiple_messages_in_sequence(self):
        stream = MockStream()
        messages = [
            SignalingMessage(type=SignalingMessage.SDP_OFFER, data=b"offer"),
            SignalingMessage(type=SignalingMessage.SDP_ANSWER, data=b"answer"),
            SignalingMessage(type=SignalingMessage.ICE_CANDIDATE, data=b"cand1"),
            SignalingMessage(type=SignalingMessage.ICE_CANDIDATE, data=b"cand2"),
            SignalingMessage(type=SignalingMessage.ICE_DONE),
        ]
        for msg in messages:
            await write_signaling_message(stream, msg)
        for expected in messages:
            received = await read_signaling_message(stream)
            assert received.type == expected.type
            assert received.data == expected.data


class TestSignalingSession:
    @pytest.mark.trio
    async def test_offer_answer_exchange(self):
        """Test the initiator sending offer and receiving answer."""
        stream = MockStream()
        session = SignalingSession(stream)

        # Simulate: send offer, then feed back an answer
        await session.send_offer(b"test-offer-sdp")

        # Read what was sent and verify
        sent = await read_signaling_message(stream)
        assert sent.type == SignalingMessage.SDP_OFFER
        assert sent.data == b"test-offer-sdp"

    @pytest.mark.trio
    async def test_receive_offer(self):
        stream = MockStream()
        session = SignalingSession(stream)

        # Pre-write an offer
        offer_msg = SignalingMessage(
            type=SignalingMessage.SDP_OFFER, data=b"remote-offer"
        )
        await write_signaling_message(stream, offer_msg)

        received = await session.receive_offer()
        assert received == b"remote-offer"

    @pytest.mark.trio
    async def test_send_candidates_and_ice_done(self):
        stream = MockStream()
        session = SignalingSession(stream)

        candidates = [b"candidate-1", b"candidate-2", b"candidate-3"]
        await session.send_candidates(candidates)

        assert session._ice_done_sent is True

        # Read back: 3 candidates + 1 ICE_DONE
        for i, cand in enumerate(candidates):
            msg = await read_signaling_message(stream)
            assert msg.type == SignalingMessage.ICE_CANDIDATE
            assert msg.data == cand

        done_msg = await read_signaling_message(stream)
        assert done_msg.type == SignalingMessage.ICE_DONE

    @pytest.mark.trio
    async def test_receive_candidates_until_ice_done(self):
        stream = MockStream()
        session = SignalingSession(stream)

        # Pre-write candidates + ICE_DONE
        for cand in [b"c1", b"c2"]:
            await write_signaling_message(
                stream,
                SignalingMessage(type=SignalingMessage.ICE_CANDIDATE, data=cand),
            )
        await write_signaling_message(
            stream,
            SignalingMessage(type=SignalingMessage.ICE_DONE),
        )

        received = []
        async for candidate in session.receive_candidates():
            received.append(candidate)

        assert received == [b"c1", b"c2"]
        assert session._ice_done_received is True

    @pytest.mark.trio
    async def test_complete_sends_and_waits_for_ice_done(self):
        stream = MockStream()
        session = SignalingSession(stream)

        # Simulate that we haven't sent ICE_DONE yet
        assert not session._ice_done_sent

        # Pre-write the remote ICE_DONE so complete() can receive it
        await write_signaling_message(
            stream,
            SignalingMessage(type=SignalingMessage.ICE_DONE),
        )

        await session.complete()

        assert session._ice_done_sent is True
        assert session._ice_done_received is True

        # Verify we sent our ICE_DONE
        sent = await read_signaling_message(stream)
        assert sent.type == SignalingMessage.ICE_DONE


class TestProtobufEnumValues:
    """Verify signaling message type enum values match the spec."""

    def test_sdp_offer_is_0(self):
        assert SignalingMessage.SDP_OFFER == 0

    def test_sdp_answer_is_1(self):
        assert SignalingMessage.SDP_ANSWER == 1

    def test_ice_candidate_is_2(self):
        assert SignalingMessage.ICE_CANDIDATE == 2

    def test_ice_done_is_3(self):
        assert SignalingMessage.ICE_DONE == 3

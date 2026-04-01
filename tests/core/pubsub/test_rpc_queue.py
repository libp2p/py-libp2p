"""Tests for libp2p.pubsub.rpc_queue — PriorityQueue, RpcQueue, and split_rpc."""

from __future__ import annotations

from collections import deque
from unittest.mock import patch

import pytest
import trio
import trio.testing

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import (
    rpc_pb2,
)
from libp2p.pubsub.rpc_queue import (
    DefaultMaxMessageSize,
    OutBoundQueueSize,
    PriorityQueue,
    RpcQueue,
    _propagate_sender_record,
    _rpc_has_data,
    _varint_size,
)
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


def _make_rpc(payload_size: int = 0) -> rpc_pb2.RPC:
    """Create an RPC with a publish message of approximately *payload_size* bytes."""
    rpc = rpc_pb2.RPC()
    if payload_size > 0:
        msg = rpc.publish.add()
        msg.data = b"x" * payload_size
    return rpc


def _make_msg(data: bytes = b"hello") -> rpc_pb2.Message:
    msg = rpc_pb2.Message()
    msg.data = data
    msg.topicIDs.append("test-topic")
    return msg


class TestPriorityQueue:
    def test_uses_deques(self) -> None:
        pq = PriorityQueue()
        assert isinstance(pq._non_priority, deque)
        assert isinstance(pq._priority, deque)

    def test_len_empty(self) -> None:
        assert len(PriorityQueue()) == 0

    def test_push_pop_non_priority(self) -> None:
        pq = PriorityQueue()
        r1, r2 = _make_rpc(), _make_rpc()
        pq.push(r1)
        pq.push(r2)
        assert len(pq) == 2
        assert pq.pop() is r1
        assert pq.pop() is r2
        assert pq.pop() is None

    def test_push_pop_priority(self) -> None:
        pq = PriorityQueue()
        r1 = _make_rpc()
        pq.push(r1, priority=True)
        assert pq.pop() is r1

    def test_priority_popped_before_non_priority(self) -> None:
        """Priority (control) items drain first, matching Go's priorityQueue.Pop."""
        pq = PriorityQueue()
        p = _make_rpc()
        np = _make_rpc()
        pq.push(p, priority=True)
        pq.push(np, priority=False)
        assert pq.pop() is p
        assert pq.pop() is np

    def test_push_rejected_when_full(self) -> None:
        """When the queue is full, push returns False (matching Go's ErrQueueFull)."""
        pq = PriorityQueue(max_size=2)
        assert pq.push(_make_rpc(), priority=False) is True
        assert pq.push(_make_rpc(), priority=True) is True
        # Queue full — new item rejected
        assert pq.push(_make_rpc(), priority=False) is False
        assert len(pq) == 2


class TestRpcQueue:
    def test_close_sets_flag(self) -> None:
        q = RpcQueue()
        assert not q.closed
        q.close()
        assert q.closed

    def test_push_on_closed_returns_false(self) -> None:
        q = RpcQueue()
        q.close()
        assert q.push(_make_rpc()) is False

    def test_len(self) -> None:
        q = RpcQueue()
        q.push(_make_rpc())
        q.push(_make_rpc())
        assert len(q) == 2

    @pytest.mark.trio
    async def test_pop_returns_pushed_item(self) -> None:
        q = RpcQueue()
        rpc = _make_rpc()
        q.push(rpc)
        result = await q.pop()
        assert result is rpc

    @pytest.mark.trio
    async def test_pop_blocks_until_push(self) -> None:
        q = RpcQueue()
        result = None

        async def consumer():
            nonlocal result
            result = await q.pop()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(consumer)
            await trio.testing.wait_all_tasks_blocked()
            assert result is None  # still blocked
            q.push(_make_rpc(10))
            # Let the consumer run
        assert result is not None

    @pytest.mark.trio
    async def test_pop_returns_none_on_close(self) -> None:
        q = RpcQueue()
        result = "sentinel"

        async def consumer():
            nonlocal result
            result = await q.pop()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(consumer)
            await trio.testing.wait_all_tasks_blocked()
            q.close()
        assert result is None

    @pytest.mark.trio
    async def test_fifo_order(self) -> None:
        q = RpcQueue()
        rpcs = [_make_rpc(i) for i in range(5)]
        for r in rpcs:
            q.push(r)
        for r in rpcs:
            assert await q.pop() is r


class TestSplitRpc:
    def test_empty_rpc_returns_no_chunks(self) -> None:
        q = RpcQueue()
        parts = q.split_rpc(rpc_pb2.RPC())
        assert len(parts) == 0

    def test_small_rpc_not_split(self) -> None:
        rpc = rpc_pb2.RPC()
        msg = rpc.publish.add()
        msg.data = b"small"
        q = RpcQueue(max_message_size=10000)
        parts = q.split_rpc(rpc)
        assert len(parts) == 1
        assert len(parts[0].publish) == 1

    def test_publish_messages_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(10):
            msg = rpc.publish.add()
            msg.data = b"x" * 100
        # Each message ~100 bytes. Set limit so only ~2 fit per chunk.
        q = RpcQueue(max_message_size=250)
        parts = q.split_rpc(rpc)
        assert len(parts) > 1
        total_msgs = sum(len(p.publish) for p in parts)
        assert total_msgs == 10

    def test_oversized_single_publish_emitted_alone(self) -> None:
        """A single message bigger than the limit must not loop forever."""
        rpc = rpc_pb2.RPC()
        msg = rpc.publish.add()
        msg.data = b"x" * 1000
        q = RpcQueue(max_message_size=100)
        parts = q.split_rpc(rpc)
        # Should produce exactly one RPC with that single message
        assert any(len(p.publish) == 1 for p in parts)

    def test_subscriptions_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(10):
            sub = rpc.subscriptions.add()
            sub.topicid = f"topic-{i}"
            sub.subscribe = True
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        assert len(parts) > 1
        total_subs = sum(len(p.subscriptions) for p in parts)
        assert total_subs == 10

    def test_ihave_split(self) -> None:
        rpc = rpc_pb2.RPC()
        ihave = rpc.control.ihave.add()
        ihave.topicID = "test"
        for i in range(20):
            ihave.messageIDs.append("msg-%d" % i)
        q = RpcQueue(max_message_size=80)
        parts = q.split_rpc(rpc)
        assert len(parts) >= 1
        # All message IDs should be preserved
        all_ids = []
        for p in parts:
            if p.HasField("control"):
                for ih in p.control.ihave:
                    all_ids.extend(ih.messageIDs)
        assert len(all_ids) == 20

    def test_iwant_split_oversized(self) -> None:
        rpc = rpc_pb2.RPC()
        iwant = rpc.control.iwant.add()
        for i in range(20):
            iwant.messageIDs.append("x" * 50)
        q = RpcQueue(max_message_size=100)
        parts = q.split_rpc(rpc)
        all_ids = []
        for p in parts:
            if p.HasField("control"):
                for iw in p.control.iwant:
                    all_ids.extend(iw.messageIDs)
        assert len(all_ids) == 20

    def test_graft_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(10):
            g = rpc.control.graft.add()
            g.topicID = f"topic-{i}"
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        total_grafts = sum(len(p.control.graft) for p in parts if p.HasField("control"))
        assert total_grafts == 10

    def test_prune_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(10):
            p = rpc.control.prune.add()
            p.topicID = f"topic-{i}"
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        total_prunes = sum(len(p.control.prune) for p in parts if p.HasField("control"))
        assert total_prunes == 10

    def test_mixed_content_preserved(self) -> None:
        """Publish + subscriptions + control all get through."""
        rpc = rpc_pb2.RPC()
        msg = rpc.publish.add()
        msg.data = b"data"
        sub = rpc.subscriptions.add()
        sub.topicid = "t"
        sub.subscribe = True
        g = rpc.control.graft.add()
        g.topicID = "t"
        q = RpcQueue(max_message_size=10000)
        parts = q.split_rpc(rpc)
        # Publish goes in its own chunk; subs + control via the fast path.
        # Verify all content is preserved across parts.
        total_publish = sum(len(p.publish) for p in parts)
        total_subs = sum(len(p.subscriptions) for p in parts)
        total_grafts = sum(len(p.control.graft) for p in parts if p.HasField("control"))
        assert total_publish == 1
        assert total_subs == 1
        assert total_grafts == 1

    def test_idontwant_split(self) -> None:
        rpc = rpc_pb2.RPC()
        idw = rpc.control.idontwant.add()
        for i in range(20):
            idw.messageIDs.append(b"x" * 50)
        q = RpcQueue(max_message_size=100)
        parts = q.split_rpc(rpc)
        all_ids = []
        for p in parts:
            if p.HasField("control"):
                for iw in p.control.idontwant:
                    all_ids.extend(iw.messageIDs)
        assert len(all_ids) == 20

    # ── edge-case: oversized single items ──

    def test_ihave_oversized_topic(self) -> None:
        """
        When the topicID alone exceeds the limit, each mid is emitted
        as an oversized solo and no empty RPCs are produced.
        """
        rpc = rpc_pb2.RPC()
        ihave = rpc.control.ihave.add()
        ihave.topicID = "t" * 200
        ihave.messageIDs.append("a")
        ihave.messageIDs.append("b")
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        all_ids: list[str] = []
        for p in parts:
            if p.HasField("control"):
                for ih in p.control.ihave:
                    all_ids.extend(ih.messageIDs)
        assert len(all_ids) == 2
        # No empty / content-free RPCs
        assert all(_rpc_has_data(p) for p in parts)

    def test_ihave_oversized_single_mid(self) -> None:
        """
        A single messageID that, combined with the topicID, exceeds the
        limit is emitted as an oversized solo.
        """
        rpc = rpc_pb2.RPC()
        ihave = rpc.control.ihave.add()
        ihave.topicID = "topic"
        ihave.messageIDs.append("x" * 200)
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        all_ids: list[str] = []
        for p in parts:
            if p.HasField("control"):
                for ih in p.control.ihave:
                    all_ids.extend(ih.messageIDs)
        assert len(all_ids) == 1
        assert all(_rpc_has_data(p) for p in parts)

    def test_iwant_oversized_single_mid(self) -> None:
        """A single oversized IWant messageID is emitted as a solo RPC."""
        rpc = rpc_pb2.RPC()
        iwant = rpc.control.iwant.add()
        iwant.messageIDs.append("x" * 200)
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        all_ids: list[str] = []
        for p in parts:
            if p.HasField("control"):
                for iw in p.control.iwant:
                    all_ids.extend(iw.messageIDs)
        assert len(all_ids) == 1
        assert all(_rpc_has_data(p) for p in parts)

    def test_idontwant_oversized_single_mid(self) -> None:
        """A single oversized IDontWant messageID is emitted as a solo."""
        rpc = rpc_pb2.RPC()
        idw = rpc.control.idontwant.add()
        idw.messageIDs.append(b"x" * 200)
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        all_ids: list[bytes] = []
        for p in parts:
            if p.HasField("control"):
                for entry in p.control.idontwant:
                    all_ids.extend(entry.messageIDs)
        assert len(all_ids) == 1
        assert all(_rpc_has_data(p) for p in parts)

    def test_no_empty_rpcs_in_split(self) -> None:
        """split_rpc never produces RPCs with no meaningful content."""
        rpc = rpc_pb2.RPC()
        ihave = rpc.control.ihave.add()
        ihave.topicID = "t" * 200
        ihave.messageIDs.append("mid")
        iwant = rpc.control.iwant.add()
        iwant.messageIDs.append("x" * 200)
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        for p in parts:
            assert _rpc_has_data(p), f"Empty RPC emitted: {p}"


class TestSizeOfEmbeddedMsg:
    def test_small_message(self) -> None:
        msg = rpc_pb2.Message()
        msg.data = b"hi"
        size = RpcQueue.size_of_embedded_msg(msg)
        # tag(1) + varint(content_size) + content_size
        content_size = msg.ByteSize()
        expected = 1 + _varint_size(content_size) + content_size
        assert size == expected

    def test_empty_message(self) -> None:
        msg = rpc_pb2.Message()
        size = RpcQueue.size_of_embedded_msg(msg)
        assert size == 1 + 1 + 0  # tag + varint(0) + 0 bytes


class TestVarintSize:
    def test_zero(self) -> None:
        assert _varint_size(0) == 1

    def test_small(self) -> None:
        assert _varint_size(1) == 1
        assert _varint_size(127) == 1

    def test_two_bytes(self) -> None:
        assert _varint_size(128) == 2
        assert _varint_size(16383) == 2

    def test_three_bytes(self) -> None:
        assert _varint_size(16384) == 3


class TestConstants:
    def test_default_max_message_size(self) -> None:
        assert DefaultMaxMessageSize == 1024 * 1024

    def test_outbound_queue_size(self) -> None:
        assert OutBoundQueueSize == 32


FAKE_SENDER_RECORD = b"\x0asigned-peer-record-bytes"


class TestSplitRpcSenderRecord:
    def test_publish_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for _ in range(10):
            rpc.publish.add().data = b"x" * 100
        rpc.senderRecord = FAKE_SENDER_RECORD

        parts = RpcQueue(max_message_size=250).split_rpc(rpc)
        assert len(parts) > 1
        assert parts[0].senderRecord == FAKE_SENDER_RECORD
        for p in parts[1:]:
            assert p.senderRecord == b""

    def test_fast_path(self) -> None:
        rpc = rpc_pb2.RPC()
        rpc.subscriptions.add().topicid = "t"
        rpc.control.graft.add().topicID = "t"
        rpc.senderRecord = FAKE_SENDER_RECORD

        parts = RpcQueue(max_message_size=10000).split_rpc(rpc)
        assert any(p.senderRecord == FAKE_SENDER_RECORD for p in parts)

    def test_slow_path(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(20):
            rpc.control.graft.add().topicID = f"topic-{i}" * 10
        rpc.senderRecord = FAKE_SENDER_RECORD

        parts = RpcQueue(max_message_size=100).split_rpc(rpc)
        assert len(parts) > 1
        assert parts[0].senderRecord == FAKE_SENDER_RECORD

    def test_size_fast_path(self) -> None:
        """SenderRecord must be counted before the fast-path size check."""
        rpc = rpc_pb2.RPC()
        rpc.subscriptions.add().topicid = "t"
        rpc.control.graft.add().topicID = "t"
        rpc.senderRecord = b"x" * 80

        parts = RpcQueue(max_message_size=100).split_rpc(rpc)
        for p in parts:
            assert p.ByteSize() <= 100

    def test_size_slow_path(self) -> None:
        """SenderRecord must be counted in slow-path accumulator checks."""
        rpc = rpc_pb2.RPC()
        for i in range(10):
            rpc.control.graft.add().topicID = f"topic-{i}" * 5
        rpc.senderRecord = b"x" * 80

        parts = RpcQueue(max_message_size=150).split_rpc(rpc)
        assert len(parts) > 1
        for p in parts:
            assert p.ByteSize() <= 150
        assert parts[0].senderRecord == rpc.senderRecord

    def test_publish_path_reserves_space(self) -> None:
        """First publish chunk accounts for senderRecord overhead."""
        rpc = rpc_pb2.RPC()
        for _ in range(4):
            rpc.publish.add().data = b"a" * 40
        rpc.senderRecord = b"S" * 60

        parts = RpcQueue(max_message_size=100).split_rpc(rpc)
        assert sum(len(p.publish) for p in parts) == 4
        assert parts[0].senderRecord == b"S" * 60
        for p in parts:
            if len(p.publish) > 1:
                assert p.ByteSize() <= 100

    def test_no_false_empty_chunk(self) -> None:
        """SenderRecord + zero publish messages must not emit a spurious chunk."""
        rpc = rpc_pb2.RPC()
        rpc.senderRecord = b"RECORD"
        rpc.subscriptions.add().topicid = "topic-a"

        parts = RpcQueue(max_message_size=10000).split_rpc(rpc)
        assert len(parts) == 1
        assert len(parts[0].publish) == 0
        assert parts[0].senderRecord == b"RECORD"

    def test_propagate_on_empty_out(self) -> None:
        original = rpc_pb2.RPC()
        original.senderRecord = FAKE_SENDER_RECORD
        result = _propagate_sender_record(original, [])
        assert len(result) == 0


class TestSplitRpcExtensions:
    def test_fast_path(self) -> None:
        rpc = rpc_pb2.RPC()
        rpc.control.extensions.topicObservation = True

        parts = RpcQueue(max_message_size=10000).split_rpc(rpc)
        assert len(parts) == 1
        assert parts[0].control.HasField("extensions")
        assert parts[0].control.extensions.topicObservation is True

    def test_slow_path_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(20):
            rpc.control.graft.add().topicID = f"topic-{i}" * 10
        rpc.control.extensions.topicObservation = True

        parts = RpcQueue(max_message_size=100).split_rpc(rpc)
        assert len(parts) > 1
        ext_count = sum(
            1
            for p in parts
            if p.HasField("control") and p.control.HasField("extensions")
        )
        assert ext_count == 1
        assert any(
            p.control.extensions.topicObservation
            for p in parts
            if p.HasField("control") and p.control.HasField("extensions")
        )

    def test_extension_only_not_filtered(self) -> None:
        rpc = rpc_pb2.RPC()
        rpc.control.extensions.topicObservation = True
        assert _rpc_has_data(rpc) is True

        parts = RpcQueue(max_message_size=10000).split_rpc(rpc)
        assert len(parts) == 1


# Integration tests


def _shrink_queues(pubsub, limit: int) -> None:
    """Lower max_message_size on every queue the node already holds."""
    for q in pubsub.peer_queues.values():
        q.max_message_size = limit


@pytest.mark.trio
async def test_publish_reaches_peer_through_split():
    """
    End-to-end: publish a message and confirm it arrives at the subscriber.
    Uses the canonical pattern: subscribe → connect → wait for mesh → publish.
    """
    async with PubsubFactory.create_batch_with_gossipsub(
        2,
    ) as pubsubs:
        topic = "split-test"
        await pubsubs[0].subscribe(topic)
        sub1 = await pubsubs[1].subscribe(topic)

        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(2)

        payload = b"A" * 100
        await pubsubs[0].publish(topic, payload)

        with trio.fail_after(5):
            msg = await sub1.get()
        assert msg.data == payload


@pytest.mark.trio
async def test_split_rpc_actually_splits_in_send_rpc():
    """
    Use real peers + real queues to prove that split_rpc produces
    multiple chunks for a large control message, and that all chunks
    are pushed to the queue.
    """
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        topic = "instrumented"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)

        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(2)

        # Shrink queues on node 0.
        _shrink_queues(pubsubs[0], 200)

        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)
        peer1_id = pubsubs[1].host.get_id()

        # Build a large control message that will need splitting.
        ctrl = rpc_pb2.ControlMessage()
        for i in range(20):
            ihave = ctrl.ihave.add()
            ihave.topicID = f"topic-{i}"
            ihave.messageIDs.extend([f"mid-{i}-{j}" for j in range(5)])

        rpc = rpc_pb2.RPC()
        rpc.control.CopyFrom(ctrl)
        rpc.senderRecord = b"X" * 50

        # Record what split_rpc returns.
        queue = pubsubs[0].peer_queues[peer1_id]
        parts = queue.split_rpc(rpc)

        assert len(parts) > 1, "Expected the RPC to be split into multiple chunks"

        # Verify all IHAVE entries are preserved across parts.
        all_mids = []
        for p in parts:
            if p.HasField("control"):
                for ih in p.control.ihave:
                    all_mids.extend(ih.messageIDs)
        assert len(all_mids) == 100  # 20 topics × 5 mids each

        # senderRecord only on the first chunk.
        assert parts[0].senderRecord == b"X" * 50
        for p in parts[1:]:
            assert p.senderRecord == b""

        # Feed through send_rpc and verify chunks were enqueued.
        initial_len = len(queue)
        router0.send_rpc(peer1_id, rpc)
        # Some chunks may be dropped (oversized solos) but at least
        # some should have been pushed.
        assert len(queue) > initial_len


@pytest.mark.trio
async def test_sender_record_reaches_peer():
    """
    Verify senderRecord is consumed by the receiving peer through the
    real publish → split_rpc → wire → receive pipeline.
    """
    captured = []

    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        topic = "sr-test"
        await pubsubs[0].subscribe(topic)
        sub1 = await pubsubs[1].subscribe(topic)

        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(2)

        import libp2p.pubsub.pubsub as pubsub_mod

        orig_fn = pubsub_mod.maybe_consume_signed_record

        def spy(rpc, host, peer_id):
            if rpc.senderRecord:
                captured.append(rpc.senderRecord)
            return orig_fn(rpc, host, peer_id)

        with patch.object(pubsub_mod, "maybe_consume_signed_record", side_effect=spy):
            await pubsubs[0].publish(topic, b"hello")

            with trio.fail_after(5):
                msg = await sub1.get()
            assert msg.data == b"hello"

        # At least one RPC received by node 1 carried a senderRecord.
        assert any(len(sr) > 0 for sr in captured)


@pytest.mark.trio
async def test_send_rpc_defers_and_piggybacks_control_on_queue_full() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        await connect(pubsubs[0].host, pubsubs[1].host)

        peer1_id = pubsubs[1].host.get_id()
        with trio.fail_after(5):
            await pubsubs[0].wait_for_peer(peer1_id)

        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)
        queue = pubsubs[0].peer_queues[peer1_id]

        for _ in range(OutBoundQueueSize):
            assert queue.push(_make_rpc(1))

        rpc = rpc_pb2.RPC()
        rpc.control.prune.add().topicID = "deferred-topic"

        router0.send_rpc(peer1_id, rpc, priority=True)

        assert peer1_id in router0._pending_control
        assert [p.topicID for p in router0._pending_control[peer1_id].prune] == [
            "deferred-topic"
        ]

        # Free queue capacity then send another RPC: deferred control should piggyback.
        while len(queue) > 0:
            assert await queue.pop() is not None
        router0.send_rpc(peer1_id, _make_rpc(5))

        assert peer1_id not in router0._pending_control
        tail_rpc = queue._queue._non_priority[-1]
        assert tail_rpc.HasField("control")
        assert [p.topicID for p in tail_rpc.control.prune] == ["deferred-topic"]


@pytest.mark.trio
async def test_send_rpc_defers_and_piggybacks_graft_and_prune_on_queue_full() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        await connect(pubsubs[0].host, pubsubs[1].host)

        peer1_id = pubsubs[1].host.get_id()
        with trio.fail_after(5):
            await pubsubs[0].wait_for_peer(peer1_id)

        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)
        queue = pubsubs[0].peer_queues[peer1_id]

        for _ in range(OutBoundQueueSize):
            assert queue.push(_make_rpc(1))

        router0.mesh["graft-topic"] = {peer1_id}

        rpc = rpc_pb2.RPC()
        rpc.control.graft.add().topicID = "graft-topic"
        rpc.control.prune.add().topicID = "prune-topic"

        router0.send_rpc(peer1_id, rpc, priority=True)

        assert peer1_id in router0._pending_control
        assert [g.topicID for g in router0._pending_control[peer1_id].graft] == [
            "graft-topic"
        ]
        assert [p.topicID for p in router0._pending_control[peer1_id].prune] == [
            "prune-topic"
        ]

        while len(queue) > 0:
            assert await queue.pop() is not None
        router0.send_rpc(peer1_id, _make_rpc(5))

        assert peer1_id not in router0._pending_control
        tail_rpc = queue._queue._non_priority[-1]
        assert [g.topicID for g in tail_rpc.control.graft] == ["graft-topic"]
        assert [p.topicID for p in tail_rpc.control.prune] == ["prune-topic"]


@pytest.mark.trio
async def test_send_rpc_defers_control_on_oversized_chunk() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        await connect(pubsubs[0].host, pubsubs[1].host)

        peer1_id = pubsubs[1].host.get_id()
        with trio.fail_after(5):
            await pubsubs[0].wait_for_peer(peer1_id)

        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)
        queue = pubsubs[0].peer_queues[peer1_id]
        queue.max_message_size = 64

        rpc = rpc_pb2.RPC()
        rpc.control.prune.add().topicID = "x" * 300

        router0.send_rpc(peer1_id, rpc, priority=True)

        assert peer1_id in router0._pending_control
        assert len(router0._pending_control[peer1_id].prune) == 1
        assert len(router0._pending_control[peer1_id].prune[0].topicID) == 300


@pytest.mark.trio
async def test_remove_peer_clears_pending_control_retry() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        await connect(pubsubs[0].host, pubsubs[1].host)

        peer1_id = pubsubs[1].host.get_id()
        with trio.fail_after(5):
            await pubsubs[0].wait_for_peer(peer1_id)

        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)

        rpc = rpc_pb2.RPC()
        rpc.control.prune.add().topicID = "drop-me"
        router0._push_control_retry(peer1_id, rpc.control)
        assert peer1_id in router0._pending_control

        router0.remove_peer(peer1_id)
        assert peer1_id not in router0._pending_control


@pytest.mark.trio
async def test_push_control_retry_ignores_non_retriable_control() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)

        peer_id = IDFactory()
        control = rpc_pb2.ControlMessage()
        control.ihave.add().topicID = "topic-a"
        control.iwant.add().messageIDs.extend(["mid-a"])
        control.idontwant.add().messageIDs.extend([b"mid-b"])

        router0._push_control_retry(peer_id, control)

        assert peer_id not in router0._pending_control


@pytest.mark.trio
async def test_push_control_retry_caps_entries_and_coalesces() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)

        peer_id = IDFactory()
        for index in range(80):
            control = rpc_pb2.ControlMessage()
            control.prune.add().topicID = f"topic-{index}"
            router0._push_control_retry(peer_id, control)

        pending = router0._pending_control[peer_id]
        assert len(pending.prune) == 64
        assert pending.prune[0].topicID == "topic-16"
        assert pending.prune[-1].topicID == "topic-79"

        extra = rpc_pb2.ControlMessage()
        extra.prune.add().topicID = "topic-extra"
        router0._push_control_retry(peer_id, extra)

        topics = [p.topicID for p in router0._pending_control[peer_id].prune]
        assert "topic-79" in topics
        assert "topic-extra" in topics


@pytest.mark.trio
async def test_filter_retriable_control_drops_stale_entries() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)

        peer_id = IDFactory()
        router0.mesh["graft-keep"] = {peer_id}
        router0.mesh["graft-drop"] = set()
        router0.mesh["prune-drop"] = {peer_id}
        router0.mesh["prune-keep"] = set()

        control = rpc_pb2.ControlMessage()
        control.graft.add().topicID = "graft-keep"
        control.graft.add().topicID = "graft-drop"
        control.prune.add().topicID = "prune-drop"
        control.prune.add().topicID = "prune-keep"
        control.prune.add().topicID = "prune-unknown"

        filtered = router0._filter_retriable_control(peer_id, control)

        assert [g.topicID for g in filtered.graft] == ["graft-keep"]
        assert [p.topicID for p in filtered.prune] == ["prune-keep", "prune-unknown"]


@pytest.mark.trio
async def test_piggyback_control_retry_cleans_all_stale_pending_entry() -> None:
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        router0 = pubsubs[0].router
        assert isinstance(router0, GossipSub)

        peer_id = IDFactory()
        router0.mesh["graft-stale"] = set()
        router0.mesh["prune-stale"] = {peer_id}

        control = rpc_pb2.ControlMessage()
        control.graft.add().topicID = "graft-stale"
        control.prune.add().topicID = "prune-stale"

        router0._push_control_retry(peer_id, control)
        assert peer_id in router0._pending_control

        outbound = rpc_pb2.RPC()
        router0._piggyback_control_retry(peer_id, outbound)

        assert peer_id not in router0._pending_control
        assert not outbound.HasField("control")

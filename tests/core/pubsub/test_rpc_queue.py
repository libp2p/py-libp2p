"""Tests for libp2p.pubsub.rpc_queue — PriorityQueue, RpcQueue, and split_rpc."""

from __future__ import annotations

from collections import deque

import pytest
import trio

from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.rpc_queue import (
    DefaultMaxMessageSize,
    OutBoundQueueSize,
    PriorityQueue,
    RpcQueue,
    _varint_size,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────


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


# ════════════════════════════════════════════════════════════════════════════
# PriorityQueue unit tests
# ════════════════════════════════════════════════════════════════════════════


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

    def test_non_priority_popped_before_priority(self) -> None:
        """Non-priority pops first (FIFO per-tier, non-priority tier first)."""
        pq = PriorityQueue()
        p = _make_rpc()
        np = _make_rpc()
        pq.push(p, priority=True)
        pq.push(np, priority=False)
        assert pq.pop() is np
        assert pq.pop() is p

    def test_drop_non_priority_first_when_full(self) -> None:
        pq = PriorityQueue(max_size=2)
        r1 = _make_rpc()  # non-priority
        r2 = _make_rpc()  # priority
        pq.push(r1, priority=False)
        pq.push(r2, priority=True)
        # Queue is full (2). Pushing another should drop oldest non-priority (r1).
        r3 = _make_rpc()
        dropped = pq.push(r3, priority=False)
        assert dropped is r1
        assert len(pq) == 2

    def test_drop_priority_when_no_non_priority(self) -> None:
        pq = PriorityQueue(max_size=1)
        r1 = _make_rpc()
        pq.push(r1, priority=True)
        r2 = _make_rpc()
        dropped = pq.push(r2, priority=True)
        assert dropped is r1

    def test_no_drop_when_under_limit(self) -> None:
        pq = PriorityQueue(max_size=10)
        assert pq.push(_make_rpc()) is None

    def test_default_max_size(self) -> None:
        pq = PriorityQueue()
        assert pq.max_size == OutBoundQueueSize


# ════════════════════════════════════════════════════════════════════════════
# RpcQueue unit tests
# ════════════════════════════════════════════════════════════════════════════


class TestRpcQueue:
    def test_close_sets_flag(self) -> None:
        q = RpcQueue()
        assert not q.closed
        q.close()
        assert q.closed

    def test_push_returns_none_when_not_full(self) -> None:
        q = RpcQueue()
        assert q.push(_make_rpc()) is None

    def test_push_on_closed_returns_none(self) -> None:
        q = RpcQueue()
        q.close()
        assert q.push(_make_rpc()) is None

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


# ════════════════════════════════════════════════════════════════════════════
# split_rpc tests
# ════════════════════════════════════════════════════════════════════════════


class TestSplitRpc:
    def test_empty_rpc_returns_single_empty(self) -> None:
        q = RpcQueue()
        parts = q.split_rpc(rpc_pb2.RPC())
        assert len(parts) == 1
        assert parts[0].ByteSize() == 0

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
            ihave.messageIDs.append(b"msg-%d" % i)
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

    def test_ihave_final_batch_not_lost(self) -> None:
        """Regression: the final IHave batch must not be silently dropped."""
        rpc = rpc_pb2.RPC()
        ihave = rpc.control.ihave.add()
        ihave.topicID = "t"
        ihave.messageIDs.append(b"only-one")
        q = RpcQueue(max_message_size=10000)
        parts = q.split_rpc(rpc)
        all_ids = []
        for p in parts:
            if p.HasField("control"):
                for ih in p.control.ihave:
                    all_ids.extend(ih.messageIDs)
        assert len(all_ids) == 1
        assert all_ids[0] == "only-one"

    def test_iwant_no_double_append(self) -> None:
        """Regression: IWant must not duplicate message IDs."""
        rpc = rpc_pb2.RPC()
        iwant = rpc.control.iwant.add()
        for i in range(5):
            iwant.messageIDs.append(b"id-%d" % i)
        q = RpcQueue(max_message_size=10000)
        parts = q.split_rpc(rpc)
        all_ids = []
        for p in parts:
            if p.HasField("control"):
                for iw in p.control.iwant:
                    all_ids.extend(iw.messageIDs)
        assert len(all_ids) == 5

    def test_iwant_split_oversized(self) -> None:
        rpc = rpc_pb2.RPC()
        iwant = rpc.control.iwant.add()
        for i in range(20):
            iwant.messageIDs.append(b"x" * 50)
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
        total_grafts = sum(
            len(p.control.graft) for p in parts if p.HasField("control")
        )
        assert total_grafts == 10

    def test_prune_split(self) -> None:
        rpc = rpc_pb2.RPC()
        for i in range(10):
            p = rpc.control.prune.add()
            p.topicID = f"topic-{i}"
        q = RpcQueue(max_message_size=50)
        parts = q.split_rpc(rpc)
        total_prunes = sum(
            len(p.control.prune) for p in parts if p.HasField("control")
        )
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
        assert len(parts) == 1
        assert len(parts[0].publish) == 1
        assert len(parts[0].subscriptions) == 1
        assert len(parts[0].control.graft) == 1

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

    def test_idontwant_not_split_when_small(self) -> None:
        rpc = rpc_pb2.RPC()
        idw = rpc.control.idontwant.add()
        idw.messageIDs.append(b"small")
        q = RpcQueue(max_message_size=10000)
        parts = q.split_rpc(rpc)
        assert len(parts) == 1
        assert len(parts[0].control.idontwant) == 1


# ════════════════════════════════════════════════════════════════════════════
# size_of_embedded_msg tests
# ════════════════════════════════════════════════════════════════════════════


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


# ════════════════════════════════════════════════════════════════════════════
# _varint_size tests
# ════════════════════════════════════════════════════════════════════════════


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


# ════════════════════════════════════════════════════════════════════════════
# Constants tests
# ════════════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_default_max_message_size(self) -> None:
        assert DefaultMaxMessageSize == 1024 * 1024

    def test_outbound_queue_size(self) -> None:
        assert OutBoundQueueSize == 5000

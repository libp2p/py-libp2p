"""
Per-peer outbound RPC queue with priority support and message splitting.

Implements the outbound message queue pattern from go-libp2p-pubsub:
- Priority queue with non-priority and priority (control) message deques
- RPC splitting to respect max message size limits
- Drop-from-front semantics when the queue is full

Reference: https://github.com/libp2p/go-libp2p-pubsub/blob/master/comm.go
"""

from __future__ import annotations

from collections import deque
import logging
from typing import Any

import trio

from .pb import rpc_pb2

logger = logging.getLogger(__name__)

# Default max RPC message size (1 MiB), matching go-libp2p-pubsub.
# Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/master/pubsub.go#L55
DefaultMaxMessageSize = 1 * 1024 * 1024

# Default outbound peer queue size (5000 messages), matching go-libp2p-pubsub.
# Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/master/pubsub.go#L58
OutBoundQueueSize = 5000


class PriorityQueue:
    """
    A bounded priority queue with two tiers: non-priority and priority.

    Uses ``collections.deque`` for O(1) popleft.  When the combined length
    reaches *max_size*, the oldest **non-priority** item is dropped first;
    if the non-priority deque is empty the oldest priority item is dropped.

    This mirrors the Go ``dropRPC`` behavior:
    https://github.com/libp2p/go-libp2p-pubsub/blob/master/comm.go
    """

    def __init__(self, max_size: int = OutBoundQueueSize) -> None:
        self.max_size = max_size
        self._non_priority: deque[rpc_pb2.RPC] = deque()
        self._priority: deque[rpc_pb2.RPC] = deque()

    def __len__(self) -> int:
        return len(self._non_priority) + len(self._priority)

    def push(self, rpc: rpc_pb2.RPC, priority: bool = False) -> rpc_pb2.RPC | None:
        """
        Push an RPC onto the queue.

        Returns the dropped RPC if the queue was full, otherwise ``None``.
        """
        dropped: rpc_pb2.RPC | None = None
        if len(self) >= self.max_size:
            dropped = self._drop_one()

        if priority:
            self._priority.append(rpc)
        else:
            self._non_priority.append(rpc)

        return dropped

    def pop(self) -> rpc_pb2.RPC | None:
        """
        Pop the oldest RPC, preferring non-priority items first.

        Returns ``None`` when both deques are empty.
        """
        if self._non_priority:
            return self._non_priority.popleft()
        if self._priority:
            return self._priority.popleft()
        return None

    def _drop_one(self) -> rpc_pb2.RPC:
        """Drop the oldest item to make room.  Prefer dropping non-priority."""
        if self._non_priority:
            return self._non_priority.popleft()
        return self._priority.popleft()


class RpcQueue:
    """
    Per-peer outbound RPC message queue.

    Wraps a :class:`PriorityQueue` and exposes an async interface via a
    ``trio.Event`` to wake the consumer whenever new messages arrive.
    Also provides :meth:`split_rpc` to break large RPCs into chunks
    that fit within *max_message_size*.

    Typical usage inside a sending loop::

        queue = RpcQueue()
        queue.push(rpc_msg)       # producer side
        rpc = await queue.pop()   # consumer side (blocks until item available)

    :param max_size: maximum number of queued RPCs before dropping.
    :param max_message_size: byte-size limit used by :meth:`split_rpc`.
    """

    def __init__(
        self,
        max_size: int = OutBoundQueueSize,
        max_message_size: int = DefaultMaxMessageSize,
    ) -> None:
        self.max_message_size = max_message_size
        self._queue = PriorityQueue(max_size)
        self._notify = trio.Event()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def __len__(self) -> int:
        return len(self._queue)

    # ------------------------------------------------------------------
    # Producer API
    # ------------------------------------------------------------------

    def push(self, rpc: rpc_pb2.RPC, priority: bool = False) -> rpc_pb2.RPC | None:
        """
        Enqueue *rpc* and wake the consumer.

        Returns any RPC that was dropped to make room, or ``None``.
        """
        if self._closed:
            return None
        dropped = self._queue.push(rpc, priority)
        # Wake up a blocked pop()
        self._notify.set()
        self._notify = trio.Event()
        return dropped

    # ------------------------------------------------------------------
    # Consumer API
    # ------------------------------------------------------------------

    async def pop(self) -> rpc_pb2.RPC | None:
        """
        Wait for and return the next RPC.

        Returns ``None`` when the queue has been closed.
        """
        while True:
            item = self._queue.pop()
            if item is not None:
                return item
            if self._closed:
                return None
            await self._notify.wait()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Signal the consumer to stop."""
        self._closed = True
        self._notify.set()

    # ------------------------------------------------------------------
    # RPC splitting
    # ------------------------------------------------------------------

    def split_rpc(self, rpc: rpc_pb2.RPC) -> list[rpc_pb2.RPC]:
        """
        Split a single RPC into a list of RPCs that each fit within
        :attr:`max_message_size`.

        The splitting strategy mirrors go-libp2p-pubsub's ``appendOrMergeRPC``
        logic — each section (publish, subscriptions, control sub-fields) is
        iterated independently and items are appended to the *current* output
        RPC until adding the next item would exceed the limit.

        **Bug-fix notes** (from issue #891):

        * Oversized single items (larger than *max_message_size* on their own)
          are emitted alone in their own RPC instead of looping infinitely.
        * IWant batches no longer double-append (the ``break`` path and the
          post-loop path were both appending the same batch).
        * The final IHave batch is no longer silently lost.
        * Size tracking uses ``ByteSize()`` on the accumulating output RPC
          directly, avoiding double-counting errors.

        :param rpc: the RPC to split.
        :return: a list of RPCs, each within *max_message_size*.
        """
        limit = self.max_message_size

        out: list[rpc_pb2.RPC] = []
        current = rpc_pb2.RPC()

        # ---- publish messages ----
        for msg in rpc.publish:
            if current.ByteSize() + msg.ByteSize() > limit:
                if current.ByteSize() > 0:
                    out.append(current)
                    current = rpc_pb2.RPC()
                # Oversized single message → emit it alone
                if msg.ByteSize() > limit:
                    solo = rpc_pb2.RPC()
                    solo.publish.append(msg)
                    out.append(solo)
                    continue
            current.publish.append(msg)

        # ---- subscriptions ----
        for sub in rpc.subscriptions:
            if current.ByteSize() + sub.ByteSize() > limit:
                if current.ByteSize() > 0:
                    out.append(current)
                    current = rpc_pb2.RPC()
                if sub.ByteSize() > limit:
                    solo = rpc_pb2.RPC()
                    solo.subscriptions.append(sub)
                    out.append(solo)
                    continue
            current.subscriptions.append(sub)

        # ---- control messages ----
        if rpc.HasField("control"):
            ctrl = rpc.control

            # -- IHAVE --
            for ihave in ctrl.ihave:
                if current.ByteSize() + ihave.ByteSize() > limit:
                    if current.ByteSize() > 0:
                        out.append(current)
                        current = rpc_pb2.RPC()
                    if ihave.ByteSize() > limit:
                        # Split individual IHAVE's messageIDs across RPCs
                        for mid in ihave.messageIDs:
                            item = rpc_pb2.ControlIHave(topicID=ihave.topicID)
                            item.messageIDs.append(mid)
                            if current.ByteSize() + item.ByteSize() > limit:
                                if current.ByteSize() > 0:
                                    out.append(current)
                                    current = rpc_pb2.RPC()
                            if not current.HasField("control"):
                                current.control.SetInParent()
                            current.control.ihave.append(item)
                        continue
                if not current.HasField("control"):
                    current.control.SetInParent()
                current.control.ihave.append(ihave)

            # -- IWANT --
            for iwant in ctrl.iwant:
                if current.ByteSize() + iwant.ByteSize() > limit:
                    if current.ByteSize() > 0:
                        out.append(current)
                        current = rpc_pb2.RPC()
                    if iwant.ByteSize() > limit:
                        # Split individual IWANT's messageIDs across RPCs
                        for mid in iwant.messageIDs:
                            item = rpc_pb2.ControlIWant()
                            item.messageIDs.append(mid)
                            if current.ByteSize() + item.ByteSize() > limit:
                                if current.ByteSize() > 0:
                                    out.append(current)
                                    current = rpc_pb2.RPC()
                            if not current.HasField("control"):
                                current.control.SetInParent()
                            current.control.iwant.append(item)
                        continue
                if not current.HasField("control"):
                    current.control.SetInParent()
                current.control.iwant.append(iwant)

            # -- GRAFT --
            for graft in ctrl.graft:
                if current.ByteSize() + graft.ByteSize() > limit:
                    if current.ByteSize() > 0:
                        out.append(current)
                        current = rpc_pb2.RPC()
                    if graft.ByteSize() > limit:
                        solo = rpc_pb2.RPC()
                        solo.control.graft.append(graft)
                        out.append(solo)
                        continue
                if not current.HasField("control"):
                    current.control.SetInParent()
                current.control.graft.append(graft)

            # -- PRUNE --
            for prune in ctrl.prune:
                if current.ByteSize() + prune.ByteSize() > limit:
                    if current.ByteSize() > 0:
                        out.append(current)
                        current = rpc_pb2.RPC()
                    if prune.ByteSize() > limit:
                        solo = rpc_pb2.RPC()
                        solo.control.prune.append(prune)
                        out.append(solo)
                        continue
                if not current.HasField("control"):
                    current.control.SetInParent()
                current.control.prune.append(prune)

            # -- IDONTWANT --
            for idontwant in ctrl.idontwant:
                if current.ByteSize() + idontwant.ByteSize() > limit:
                    if current.ByteSize() > 0:
                        out.append(current)
                        current = rpc_pb2.RPC()
                    if idontwant.ByteSize() > limit:
                        # Split individual IDONTWANT's messageIDs across RPCs
                        for mid in idontwant.messageIDs:
                            item = rpc_pb2.ControlIDontWant()
                            item.messageIDs.append(mid)
                            if current.ByteSize() + item.ByteSize() > limit:
                                if current.ByteSize() > 0:
                                    out.append(current)
                                    current = rpc_pb2.RPC()
                            if not current.HasField("control"):
                                current.control.SetInParent()
                            current.control.idontwant.append(item)
                        continue
                if not current.HasField("control"):
                    current.control.SetInParent()
                current.control.idontwant.append(idontwant)

        # ---- flush remaining ----
        if current.ByteSize() > 0:
            out.append(current)

        return out if out else [rpc_pb2.RPC()]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def size_of_embedded_msg(msg: Any) -> int:
        """
        Return the wire size of *msg* when embedded inside a protobuf
        container (tag byte + varint length prefix + content bytes).
        """
        s = msg.ByteSize()
        return 1 + _varint_size(s) + s


def _varint_size(value: int) -> int:
    """Return the number of bytes needed to encode *value* as a varint."""
    if value == 0:
        return 1
    size = 0
    while value > 0:
        size += 1
        value >>= 7
    return size

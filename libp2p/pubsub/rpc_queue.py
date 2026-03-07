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

# Default outbound peer queue size, matching go-libp2p-pubsub.
# Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/master/pubsub.go
OutBoundQueueSize = 32

# Protobuf field tag size for field numbers < 15 (1 byte: fieldNumber<<3|wireType).
# Ref: https://protobuf.dev/programming-guides/encoding/#structure
_PB_FIELD_LT15_SIZE = 1


class PriorityQueue:
    """
    A bounded priority queue with two tiers: non-priority and priority.

    Uses ``collections.deque`` for O(1) popleft.  When the combined length
    reaches *max_size*, pushes are **rejected** (the new item is not added).
    This matches go-libp2p-pubsub where a full queue returns ``ErrQueueFull``
    and the *caller* decides how to handle the rejected RPC (e.g. log it,
    save GRAFT/PRUNE for retry).

    Reference: https://github.com/libp2p/go-libp2p-pubsub/blob/master/rpc_queue.go
    """

    def __init__(self, max_size: int = OutBoundQueueSize) -> None:
        self.max_size = max_size
        self._non_priority: deque[rpc_pb2.RPC] = deque()
        self._priority: deque[rpc_pb2.RPC] = deque()

    def __len__(self) -> int:
        return len(self._non_priority) + len(self._priority)

    def push(self, rpc: rpc_pb2.RPC, priority: bool = False) -> bool:
        """
        Push an RPC onto the queue.

        Returns ``True`` if the item was enqueued, ``False`` if the queue
        is full (matching Go's ``ErrQueueFull``).
        """
        if len(self) >= self.max_size:
            return False

        if priority:
            self._priority.append(rpc)
        else:
            self._non_priority.append(rpc)

        return True

    def pop(self) -> rpc_pb2.RPC | None:
        """
        Pop the oldest RPC, preferring **priority** items first.

        This matches go-libp2p-pubsub's ``priorityQueue.Pop`` which drains
        the priority (control) deque before the normal deque so that
        control messages are sent ahead of bulk data.

        Returns ``None`` when both deques are empty.
        """
        if self._priority:
            return self._priority.popleft()
        if self._non_priority:
            return self._non_priority.popleft()
        return None


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

    def push(self, rpc: rpc_pb2.RPC, priority: bool = False) -> bool:
        """
        Enqueue *rpc* and wake the consumer.

        Returns ``True`` if the item was enqueued, ``False`` if the queue
        is full or closed.  When ``False`` is returned the caller should
        handle the rejected RPC (matching Go's ``doDropRPC``).
        """
        if self._closed:
            return False
        ok = self._queue.push(rpc, priority)
        if ok:
            # Wake up a blocked pop()
            self._notify.set()
            self._notify = trio.Event()
        return ok

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

    def close(self) -> None:
        """Signal the consumer to stop."""
        self._closed = True
        self._notify.set()

    def split_rpc(self, rpc: rpc_pb2.RPC) -> list[rpc_pb2.RPC]:
        """
        Split a single RPC into a list of RPCs that each fit within
        :attr:`max_message_size`.

        The strategy is a **faithful port** of go-libp2p-pubsub's
        ``RPC.split`` method (``pubsub.go``).  The pattern for every
        section is:

        1. Append item to the current accumulator RPC.
        2. If ``current.ByteSize() > limit``, **undo** the append,
           yield ``current``, start a fresh accumulator with that item.
        3. No "solo guard" — if a single atomic item exceeds the limit
           it stays in the accumulator and gets yielded as-is.
           The **caller** is responsible for detecting and dropping
           oversized chunks (matching Go's ``sendRPC`` loop).

        Sections handled (in order): Publish, Subscriptions,
        Graft, Prune, IWant, IHave, IDontWant.

        **Note:** Go's ``split`` does *not* handle IDontWant — it only
        survives via the fast path.  We add an explicit IDontWant section
        (using the same append→check→undo→yield pattern) so that large
        IDontWant payloads are preserved even when the RPC is too big
        for the fast path.

        :param rpc: the RPC to split.
        :return: a list of RPCs, each ideally within *max_message_size*
                 (oversized single items are yielded for the caller to
                 drop).
        """
        limit = self.max_message_size

        out: list[rpc_pb2.RPC] = []
        current = rpc_pb2.RPC()

        # ── Publish messages (optimised incremental size tracking) ──
        # Mirrors Go's optimised publish path that avoids calling
        # .Size() repeatedly on accumulated messages.
        current_size = 0
        messages_in_current = 0
        publish_list = list(rpc.publish)  # snapshot for slicing

        for i, msg in enumerate(publish_list):
            incremental = _PB_FIELD_LT15_SIZE + self.size_of_embedded_msg(msg)
            if current_size + incremental > limit:
                # Yield what we have so far
                current.publish.extend(publish_list[i - messages_in_current : i])
                if messages_in_current > 0:
                    out.append(current)
                    current = rpc_pb2.RPC()
                current_size = 0
                messages_in_current = 0
            messages_in_current += 1
            current_size += incremental

        if current_size > 0:
            # Yield the remaining publish messages
            start = len(publish_list) - messages_in_current
            current.publish.extend(publish_list[start:])
            out.append(current)
            current = rpc_pb2.RPC()

        # ── Fast path ──
        # After publish messages are handled, check whether the rest
        # of the original RPC (subs + control) fits in one chunk.
        # This mirrors Go's ``nextRPC = *rpc; nextRPC.Publish = nil``
        # optimisation.
        rest = rpc_pb2.RPC()
        rest.subscriptions.extend(rpc.subscriptions)
        if rpc.HasField("control"):
            rest.control.CopyFrom(rpc.control)
        rest_size = rest.ByteSize()
        if rest_size > 0 and rest_size <= limit:
            out.append(rest)
            return out if out else [rpc_pb2.RPC()]

        # The rest doesn't fit — split it section by section.
        if rest_size == 0:
            return out if out else [rpc_pb2.RPC()]

        current = rpc_pb2.RPC()

        # ── Subscriptions ──
        for sub in rpc.subscriptions:
            current.subscriptions.append(sub)
            if current.ByteSize() > limit:
                del current.subscriptions[-1]
                out.append(current)
                current = rpc_pb2.RPC()
                current.subscriptions.append(sub)

        # ── Control messages ──
        if rpc.HasField("control"):
            ctrl = rpc.control

            # Initialise the control wrapper (matching Go's explicit check)
            if not current.HasField("control"):
                current.control.SetInParent()
                if current.ByteSize() > limit:
                    current.control.ClearField("control")
                    out.append(current)
                    current = rpc_pb2.RPC()
                    current.control.SetInParent()

            # GRAFT
            for graft in ctrl.graft:
                current.control.graft.append(graft)
                if current.ByteSize() > limit:
                    del current.control.graft[-1]
                    out.append(current)
                    current = rpc_pb2.RPC()
                    current.control.SetInParent()
                    current.control.graft.append(graft)

            # PRUNE
            for prune in ctrl.prune:
                current.control.prune.append(prune)
                if current.ByteSize() > limit:
                    del current.control.prune[-1]
                    out.append(current)
                    current = rpc_pb2.RPC()
                    current.control.SetInParent()
                    current.control.prune.append(prune)

            # IWANT — coalesce into a single ControlIWant
            for iwant in ctrl.iwant:
                if not current.control.iwant:
                    new_iwant = rpc_pb2.ControlIWant()
                    current.control.iwant.append(new_iwant)
                    if current.ByteSize() > limit:
                        del current.control.iwant[-1]
                        out.append(current)
                        current = rpc_pb2.RPC()
                        current.control.SetInParent()
                        current.control.iwant.append(
                            rpc_pb2.ControlIWant()
                        )

                for mid in iwant.messageIDs:
                    current.control.iwant[0].messageIDs.append(mid)
                    if current.ByteSize() > limit:
                        del current.control.iwant[0].messageIDs[-1]
                        out.append(current)
                        current = rpc_pb2.RPC()
                        current.control.SetInParent()
                        current.control.iwant.append(
                            rpc_pb2.ControlIWant(
                                messageIDs=[mid],
                            )
                        )

            # IHAVE — coalesce by topicID
            for ihave in ctrl.ihave:
                ihave_list = current.control.ihave
                if (
                    not ihave_list
                    or ihave_list[-1].topicID != ihave.topicID
                ):
                    new_ihave = rpc_pb2.ControlIHave(
                        topicID=ihave.topicID
                    )
                    ihave_list.append(new_ihave)
                    if current.ByteSize() > limit:
                        del ihave_list[-1]
                        out.append(current)
                        current = rpc_pb2.RPC()
                        current.control.SetInParent()
                        current.control.ihave.append(new_ihave)

                for mid in ihave.messageIDs:
                    last_ihave = current.control.ihave[-1]
                    last_ihave.messageIDs.append(mid)
                    if current.ByteSize() > limit:
                        del last_ihave.messageIDs[-1]
                        out.append(current)
                        current = rpc_pb2.RPC()
                        current.control.SetInParent()
                        current.control.ihave.append(
                            rpc_pb2.ControlIHave(
                                topicID=ihave.topicID,
                                messageIDs=[mid],
                            )
                        )

            # IDONTWANT — coalesce into a single ControlIDontWant
            # (Not in Go's split, but we keep it so oversized IDontWant
            #  payloads aren't silently dropped when the fast path misses.)
            for idontwant in ctrl.idontwant:
                if not current.control.idontwant:
                    new_idw = rpc_pb2.ControlIDontWant()
                    current.control.idontwant.append(new_idw)
                    if current.ByteSize() > limit:
                        del current.control.idontwant[-1]
                        out.append(current)
                        current = rpc_pb2.RPC()
                        current.control.SetInParent()
                        current.control.idontwant.append(
                            rpc_pb2.ControlIDontWant()
                        )

                for mid in idontwant.messageIDs:
                    current.control.idontwant[0].messageIDs.append(mid)
                    if current.ByteSize() > limit:
                        del current.control.idontwant[0].messageIDs[-1]
                        out.append(current)
                        current = rpc_pb2.RPC()
                        current.control.SetInParent()
                        current.control.idontwant.append(
                            rpc_pb2.ControlIDontWant(
                                messageIDs=[mid],
                            )
                        )

        # ── Flush remaining ──
        if current.ByteSize() > 0:
            out.append(current)

        # Filter out RPCs that only contain an empty control wrapper
        # (can happen when the first item in a section already exceeds the
        # limit, causing the accumulator with just ``control {}`` to be
        # yielded).
        out = [r for r in out if _rpc_has_data(r)]

        return out if out else [rpc_pb2.RPC()]

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


def _rpc_has_data(rpc: rpc_pb2.RPC) -> bool:
    """Return ``True`` if *rpc* carries any meaningful content.

    Used by tests and callers to verify that :func:`split_rpc` never
    emits completely empty RPCs.
    """
    if rpc.publish or rpc.subscriptions:
        return True
    if rpc.HasField("control"):
        ctrl = rpc.control
        if ctrl.graft or ctrl.prune or ctrl.iwant or ctrl.ihave or ctrl.idontwant:
            return True
    return False

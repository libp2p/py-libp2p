"""
Bitswap MessageQueue for managing persistent outbound streams and
debounced message batching.

Matches the Kubo (go-bitswap/messagequeue) architecture:
- Maintains at most 1 persistent outbound stream per peer.
- Coalesces and batches wantlists, cancels, block presences, and data blocks.
- Applies a short debounce window (10ms-20ms) to merge rapid updates into
  a single write frame.
- Automatically handles stream reconnection on errors without dialing
  per-message streams.
"""

from collections.abc import Sequence
import logging
from typing import Any

import trio
import varint

from libp2p.abc import IHost, INetStream
from libp2p.bitswap.cid import CIDObject
from libp2p.bitswap.config import (
    MAX_MESSAGE_SIZE,
    MAX_PENDING_BLOCK_BYTES_PER_PEER,
    MAX_PENDING_BLOCKS_PER_PEER,
    MAX_PENDING_WANTS_PER_PEER,
)
from libp2p.bitswap.events import BitswapEvent
from libp2p.bitswap.messages import create_message, create_wantlist_entry
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID as PeerID

logger = logging.getLogger("libp2p.bitswap.message_queue")


class BitswapMessageQueue:
    """
    Manages an outgoing stream pipeline to a single peer.
    """

    def __init__(
        self,
        host: IHost,
        peer_id: PeerID,
        supported_protocols: Sequence[str],
        on_stream_opened: Any | None = None,
        debounce_delay: float = 0.015,
    ) -> None:
        self.host = host
        self.peer_id = peer_id
        self.supported_protocols = list(supported_protocols)
        self.on_stream_opened = on_stream_opened
        self.debounce_delay = debounce_delay

        self._stream: INetStream | None = None
        self._lock = trio.Lock()
        self._notify_event = trio.Event()
        self._cancel_scope = trio.CancelScope()
        self._started = False
        self.negotiated_protocol: str | None = None

        # Retry backoff for transient dial/stream failures. A failed flush
        # requeues its payload and retries with exponential backoff instead of
        # silently dropping wants/blocks (which left peers hanging forever).
        self._retry_delay = 0.25
        self._initial_retry_delay = 0.25
        self._max_retry_delay = 30.0

        # Buffers for coalescing messages
        self._pending_wants: dict[CIDObject, dict[str, Any]] = {}
        self._pending_cancels: set[CIDObject] = set()
        self._pending_presences: dict[CIDObject, bool] = {}
        self._pending_blocks_v100: list[bytes] = []
        self._pending_blocks_v110: list[tuple[bytes, bytes]] = []
        self._full_wantlist: bool = False

    def start(self, nursery: trio.Nursery) -> None:
        """Start the background worker loop in the given nursery."""
        if self._started:
            return
        self._started = True
        nursery.start_soon(self._worker_loop)

    async def stop(self) -> None:
        """Stop the worker loop and close the stream."""
        if not self._started:
            return
        self._started = False
        self._cancel_scope.cancel()
        with trio.move_on_after(2.0):
            async with self._lock:
                if self._stream is not None:
                    try:
                        await self._stream.close()
                    except Exception:
                        pass
                    self._stream = None

    def add_wants(
        self,
        cids: Sequence[CIDObject],
        want_infos: dict[CIDObject, dict[str, Any]] | None = None,
        full_wantlist: bool = False,
    ) -> None:
        """Queue wantlist entries for transmission."""
        if full_wantlist:
            self._full_wantlist = True
        for cid in cids:
            # If CID was previously marked for cancel, remove cancel
            self._pending_cancels.discard(cid)
            info = want_infos.get(cid, {}) if want_infos else {}
            self._pending_wants[cid] = {
                "priority": info.get("priority", 1),
                "want_type": info.get("want_type", 0),
                "send_dont_have": info.get("send_dont_have", False),
            }
        self._trim_pending_wants(full_wantlist=full_wantlist)
        self._notify_event.set()

    def _trim_pending_wants(self, *, full_wantlist: bool) -> None:
        """Bound queued wants, dropping the oldest incremental entries."""
        if full_wantlist:
            # A full wantlist is a snapshot; trimming it would silently
            # change its meaning. Callers construct bounded snapshots.
            return
        while len(self._pending_wants) > MAX_PENDING_WANTS_PER_PEER:
            self._pending_wants.pop(next(iter(self._pending_wants)))

    def _trim_pending_blocks(self) -> None:
        """Bound queued blocks by both entry count and total payload bytes."""
        blocks_v100 = self._pending_blocks_v100
        blocks_v110 = self._pending_blocks_v110
        total_entries = len(blocks_v100) + len(blocks_v110)
        total_bytes = sum(map(len, blocks_v100)) + sum(
            len(prefix) + len(data) for prefix, data in blocks_v110
        )

        while total_entries > MAX_PENDING_BLOCKS_PER_PEER:
            if blocks_v100:
                total_bytes -= len(blocks_v100.pop(0))
            elif blocks_v110:
                prefix, data = blocks_v110.pop(0)
                total_bytes -= len(prefix) + len(data)
            else:
                break
            total_entries -= 1

        while total_bytes > MAX_PENDING_BLOCK_BYTES_PER_PEER:
            if blocks_v100:
                total_bytes -= len(blocks_v100.pop(0))
            elif blocks_v110:
                prefix, data = blocks_v110.pop(0)
                total_bytes -= len(prefix) + len(data)
            else:
                break

    def add_cancels(self, cids: Sequence[CIDObject]) -> None:
        """Queue cancel entries for transmission."""
        for cid in cids:
            self._pending_wants.pop(cid, None)
            self._pending_cancels.add(cid)
        self._notify_event.set()

    def add_presences(self, presences: Sequence[tuple[CIDObject, bool]]) -> None:
        """Queue block presences (Have / DontHave) for transmission."""
        for cid, has_block in presences:
            self._pending_presences[cid] = has_block
        self._notify_event.set()

    def add_blocks_v100(self, blocks: Sequence[bytes]) -> None:
        """Queue v1.0.0 raw data blocks for transmission."""
        self._pending_blocks_v100.extend(blocks)
        self._trim_pending_blocks()
        self._notify_event.set()

    def add_blocks_v110(self, blocks: Sequence[tuple[bytes, bytes]]) -> None:
        """Queue v1.1.0+ (prefix, data) blocks for transmission."""
        self._pending_blocks_v110.extend(blocks)
        self._trim_pending_blocks()
        self._notify_event.set()

    async def _get_or_open_stream(self) -> INetStream | None:
        """Return the active outbound stream or establish a new one."""
        if self._stream is not None:
            # Check if stream is still alive and writable
            muxed = getattr(self._stream, "muxed_stream", None)
            if muxed is not None:
                state = getattr(self._stream, "_state", None)
                state_name = getattr(state, "name", "")
                if state_name in ("OPEN", "INIT", "CLOSE_READ"):
                    return self._stream
            self._stream = None

        # Try to open a new stream
        protocols = (
            [TProtocol(self.negotiated_protocol)]
            if self.negotiated_protocol
            else [TProtocol(p) for p in self.supported_protocols]
        )
        try:
            stream = await self.host.new_stream(self.peer_id, protocols)
            proto = stream.get_protocol()
            if proto:
                self.negotiated_protocol = str(proto)
            self._stream = stream
            if self.on_stream_opened is not None:
                try:
                    self.on_stream_opened(stream, self.peer_id)
                except Exception:
                    pass
            return stream
        except Exception as e:
            logger.debug(f"Failed to open Bitswap stream to {self.peer_id}: {e}")
            self._stream = None
            return None

    async def _worker_loop(self) -> None:
        """Background loop that debounces and flushes outgoing messages."""
        try:
            with self._cancel_scope:
                while self._started:
                    await self._notify_event.wait()
                    self._notify_event = trio.Event()

                    # Debounce window to coalesce rapid sequential additions
                    if self.debounce_delay > 0:
                        await trio.sleep(self.debounce_delay)

                    ok = await self.flush()
                    if not ok:
                        # flush() requeued the payload; back off before the
                        # next attempt so transient failures don't hot-loop.
                        await trio.sleep(self._retry_delay)
                        self._retry_delay = min(
                            self._retry_delay * 2, self._max_retry_delay
                        )
                        if self._has_pending():
                            self._notify_event.set()
                    else:
                        self._retry_delay = self._initial_retry_delay
        except trio.Cancelled:
            pass

    def _has_pending(self) -> bool:
        """True if any coalesced payload is awaiting transmission."""
        return bool(
            self._pending_wants
            or self._pending_cancels
            or self._pending_presences
            or self._pending_blocks_v100
            or self._pending_blocks_v110
            or self._full_wantlist
        )

    async def flush(self) -> bool:
        """
        Snapshot, drain, and send all pending items over the stream.

        Returns True when the payload was handed to the transport. On failure
        the drained items are requeued, so a transient dial or stream error
        cannot silently drop wants/blocks.
        """
        async with self._lock:
            wants: dict[CIDObject, dict[str, Any]] = {
                k: v for k, v in self._pending_wants.items()
            }
            self._pending_wants.clear()

            cancels = set(self._pending_cancels)
            self._pending_cancels.clear()

            presences = list(self._pending_presences.items())
            self._pending_presences.clear()

            blocks_v100 = list(self._pending_blocks_v100)
            self._pending_blocks_v100.clear()

            blocks_v110 = list(self._pending_blocks_v110)
            self._pending_blocks_v110.clear()

            full_wantlist = self._full_wantlist
            self._full_wantlist = False

        if not (
            wants or cancels or presences or blocks_v100 or blocks_v110 or full_wantlist
        ):
            return True

        # Prepare wantlist entries
        entries = []
        for cid, info in wants.items():
            entries.append(
                create_wantlist_entry(
                    cid,
                    priority=int(info.get("priority", 1)),
                    cancel=False,
                    want_type=int(info.get("want_type", 0)),
                    send_dont_have=bool(info.get("send_dont_have", False)),
                )
            )
        for cid in cancels:
            entries.append(
                create_wantlist_entry(
                    cid,
                    priority=1,
                    cancel=True,
                )
            )

        # Stream and send messages in chunks under MAX_MESSAGE_SIZE
        ok = await self._flush_messages(
            entries=entries,
            presences=presences,
            blocks_v100=blocks_v100,
            blocks_v110=blocks_v110,
            full_wantlist=full_wantlist,
        )
        if not ok:
            # Requeue everything so the next cycle retries instead of losing
            # the payload (wants that were never sent leave peers hanging).
            async with self._lock:
                for cid, info in wants.items():
                    self._pending_wants[cid] = info
                for cid in cancels:
                    self._pending_cancels.add(cid)
                for cid, has_block in presences:
                    self._pending_presences[cid] = has_block
                self._pending_blocks_v100 = blocks_v100 + self._pending_blocks_v100
                self._pending_blocks_v110 = blocks_v110 + self._pending_blocks_v110
                self._trim_pending_blocks()
                if full_wantlist and (wants or cancels or presences):
                    self._full_wantlist = True
        return ok

    async def _flush_messages(
        self,
        entries: list[Any],
        presences: list[tuple[CIDObject, bool]],
        blocks_v100: list[bytes],
        blocks_v110: list[tuple[bytes, bytes]],
        full_wantlist: bool,
    ) -> bool:
        """
        Send all batched messages over the reused stream.

        Returns False (without sending) if no stream can be opened or a write
        fails; the caller requeues the payload for a later retry.
        """
        stream = await self._get_or_open_stream()
        if stream is None:
            # Peer unreachable or stream negotiation failed
            return False

        try:
            # 1. Send wantlist entries and block presences
            if entries or presences or full_wantlist:
                msg = create_message(
                    wantlist_entries=entries if entries else None,
                    block_presences=presences if presences else None,
                    full_wantlist=full_wantlist,
                )
                await self._write_protobuf_message(stream, msg)

            # 2. Send v1.0.0 blocks (chunked if large)
            if blocks_v100:
                current_batch: list[bytes] = []
                current_size = 0
                for block in blocks_v100:
                    if current_batch and (current_size + len(block) > 60_000):
                        msg = create_message(blocks_v100=current_batch)
                        await self._write_protobuf_message(stream, msg)
                        current_batch = []
                        current_size = 0
                    current_batch.append(block)
                    current_size += len(block)
                if current_batch:
                    msg = create_message(blocks_v100=current_batch)
                    await self._write_protobuf_message(stream, msg)

            # 3. Send v1.1.0+ blocks (chunked if large)
            if blocks_v110:
                current_v110_batch: list[tuple[bytes, bytes]] = []
                current_v110_size = 0
                for prefix, block_data in blocks_v110:
                    item_size = len(prefix) + len(block_data)
                    if current_v110_batch and (current_v110_size + item_size > 60_000):
                        msg = create_message(blocks_v110=current_v110_batch)
                        await self._write_protobuf_message(stream, msg)
                        current_v110_batch = []
                        current_v110_size = 0
                    current_v110_batch.append((prefix, block_data))
                    current_v110_size += item_size
                if current_v110_batch:
                    msg = create_message(blocks_v110=current_v110_batch)
                    await self._write_protobuf_message(stream, msg)

            # Emit message-sent metric event (one per flush, summarizing the
            # batched content that was written to the wire).
            kind = "wantlist" if (entries or presences or full_wantlist) else "blocks"
            event = BitswapEvent()
            event.peer_id = str(self.peer_id)
            event.message_sent = True
            event.kind = kind
            event.entries = len(entries)
            self.host.get_event_bus().emit(event)
            return True

        except Exception as e:
            logger.debug(f"Error writing to Bitswap stream for {self.peer_id}: {e}")
            # Invalidate stream on write error so next cycle reconnects
            async with self._lock:
                if self._stream is stream:
                    try:
                        await stream.close()
                    except Exception:
                        pass
                    self._stream = None
            return False

    async def _write_protobuf_message(self, stream: INetStream, msg: Any) -> None:
        """Serialize and write a varint length-prefixed protobuf message."""
        msg_bytes = msg.SerializeToString()
        if len(msg_bytes) > MAX_MESSAGE_SIZE:
            logger.warning(
                f"Bitswap message size {len(msg_bytes)} exceeds {MAX_MESSAGE_SIZE}"
            )
        prefix = varint.encode(len(msg_bytes))
        await stream.write(prefix + msg_bytes)

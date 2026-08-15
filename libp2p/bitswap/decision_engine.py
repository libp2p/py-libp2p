"""
Bitswap Decision Engine for scheduling block delivery and presence responses.

Matches Kubo (boxo/bitswap/server/internal/decision):
- Processes incoming peer wantlists with backpressure and concurrency limits.
- Drops DontHave queries when sendDontHave is False (preventing network spam).
- Forwards positive block deliveries to a bounded worker pool.
- Coordinates with BitswapMessageQueue for debounced, persistent stream transmission.
"""

import logging
from typing import Any, Callable

import trio

from libp2p.bitswap.block_store import BlockStore
from libp2p.bitswap.cid import CIDObject, format_cid_for_display, get_cid_prefix
from libp2p.bitswap.config import BITSWAP_PROTOCOL_V100
from libp2p.bitswap.message_queue import BitswapMessageQueue
from libp2p.peer.id import ID as PeerID

logger = logging.getLogger("libp2p.bitswap.decision_engine")


class BitswapDecisionEngine:
    """
    Decides how to process and schedule responses to incoming wantlists.
    """

    def __init__(
        self,
        block_store: BlockStore,
        get_message_queue_fn: Callable[[PeerID], BitswapMessageQueue],
        num_workers: int = 8,
    ) -> None:
        self.block_store = block_store
        self.get_message_queue = get_message_queue_fn
        self.num_workers = num_workers

        self._send_channel, self._receive_channel = trio.open_memory_channel[
            tuple[PeerID, CIDObject, str]
        ](500)
        self._started = False

    def start(self, nursery: trio.Nursery) -> None:
        """Start the worker pool."""
        if self._started:
            return
        self._started = True
        for i in range(self.num_workers):
            nursery.start_soon(self._worker_loop, i)

    async def stop(self) -> None:
        """Stop all workers."""
        if not self._started:
            return
        self._started = False
        try:
            await self._send_channel.aclose()
        except Exception:
            pass
        try:
            await self._receive_channel.aclose()
        except Exception:
            pass

    async def handle_wantlist_entries(
        self,
        peer_id: PeerID,
        peer_protocol: str,
        entries: list[Any],
    ) -> None:
        """
        Process a batch of incoming wantlist entries from a peer.
        """
        presences_to_send: list[tuple[CIDObject, bool]] = []
        blocks_to_schedule: list[tuple[PeerID, CIDObject, str]] = []

        for entry in entries:
            entry_cid = getattr(entry, "cid_obj", None)
            if entry_cid is None:
                continue

            if getattr(entry, "cancel", False):
                # Remote peer canceled their want
                continue

            want_type = getattr(entry, "wantType", 0)
            send_dont_have = getattr(entry, "sendDontHave", False)

            # Check if block is stored locally
            try:
                has_block = await self.block_store.has_block(entry_cid)
            except Exception:
                has_block = False

            if has_block:
                logger.debug(
                    f"Peer {peer_id} wants available block "
                    f"{format_cid_for_display(entry_cid, max_len=16)}"
                )
                blocks_to_schedule.append((peer_id, entry_cid, peer_protocol))
            else:
                # We do not have the block.
                # Only reply with DontHave if the peer asked for it (v1.2.0 spec).
                if want_type == 1:  # WANT_HAVE
                    presences_to_send.append((entry_cid, False))
                elif send_dont_have:  # WANT_BLOCK with sendDontHave=True
                    presences_to_send.append((entry_cid, False))

        # 1. Forward DontHave presences to the peer's MessageQueue for debounced batching
        if presences_to_send:
            try:
                msg_queue = self.get_message_queue(peer_id)
                msg_queue.add_presences(presences_to_send)
                if not msg_queue._started:
                    await msg_queue.flush()
            except Exception as e:
                logger.debug(
                    f"Failed to queue presences for {peer_id}: {e}"
                )

        # 2. Schedule block delivery tasks
        for task in blocks_to_schedule:
            if self._started:
                try:
                    self._send_channel.send_nowait(task)
                except (trio.WouldBlock, trio.ClosedResourceError):
                    logger.warning(
                        f"DecisionEngine task queue full; dropping block task for {peer_id}"
                    )
            else:
                # Standalone fallback when no nursery worker loop is attached
                await self._process_task(*task)

    async def _process_task(
        self, peer_id: PeerID, cid: CIDObject, peer_proto: str
    ) -> None:
        """Process a single block delivery task."""
        try:
            data = await self.block_store.get_block(cid)
            if not data:
                return

            msg_queue = self.get_message_queue(peer_id)
            if peer_proto == BITSWAP_PROTOCOL_V100:
                msg_queue.add_blocks_v100([data])
            else:
                prefix = get_cid_prefix(cid)
                msg_queue.add_blocks_v110([(prefix, data)])

            if not msg_queue._started:
                await msg_queue.flush()

            logger.debug(
                f"Queued block {format_cid_for_display(cid)} "
                f"({len(data)} bytes) for {peer_id}"
            )
        except Exception as e:
            logger.debug(
                f"Error preparing block for {peer_id}: {e}"
            )

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker task that retrieves blocks and pushes them to MessageQueue."""
        while self._started:
            try:
                peer_id, cid, peer_proto = await self._receive_channel.receive()
            except (trio.EndOfChannel, trio.ClosedResourceError, trio.Cancelled):
                break

            await self._process_task(peer_id, cid, peer_proto)

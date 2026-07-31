import logging
import random
import time
from typing import TYPE_CHECKING

import trio

from libp2p.peer.id import ID as PeerID

from .cid import CIDObject, format_cid_for_display, parse_cid
from .config import DEFAULT_TIMEOUT
from .errors import TimeoutError as BitswapTimeoutError

if TYPE_CHECKING:
    from .client import BitswapClient
    from .cid import CIDInput

logger = logging.getLogger("libp2p.bitswap.session")

# How often to rebroadcast WANT_HAVE for undiscovered blocks (seconds)
REBROADCAST_INTERVAL = 5.0
# How many peers to race in parallel for a single block
MAX_PARALLEL_RACE = 3


class BitswapSession:
    """
    A Session scopes the retrieval of a set of related blocks (like a file).
    It isolates the network state and routes requests efficiently.

    Implements:
      - WANT-HAVE → WANT-BLOCK phasing (cheap presence check first)
      - Parallel peer racing (request from multiple peers simultaneously)
      - Periodic wantlist rebroadcasting (prevent want starvation)
    """

    def __init__(self, client: "BitswapClient", session_id: int):
        self.client = client
        self.id = session_id
        # Map CID to the events waiting for it *in this session*
        self._pending_requests: dict[CIDObject, set[trio.Event]] = {}
        # Track peers that have provided data
        self.active_peers: set[PeerID] = set()

    async def get_block(
        self,
        cid: "CIDInput",
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        """Get a single block via this session."""
        cid_obj = parse_cid(cid)

        # 1. Check local store first
        data = await self.client.block_store.get_block(cid_obj)
        if data is not None:
            return data

        # 2. Try DHT discovery if peer_id is not given
        if peer_id is None and self.client.provider_query_manager is not None:
            try:
                providers = (
                    await self.client.provider_query_manager.find_providers_single(
                        cid, timeout=min(5.0, timeout / 2)
                    )
                )
                if providers:
                    peer_id = providers[0]
                    logger.debug(
                        "Session %s: DHT discovered provider %s for %s",
                        self.id,
                        peer_id,
                        format_cid_for_display(cid_obj, max_len=12),
                    )
            except Exception as exc:
                logger.debug(
                    "Session %s: Provider query failed, falling back to broadcast: %s",
                    self.id,
                    exc,
                )

        return await self._request_block(cid_obj, peer_id, timeout)

    async def _request_block(
        self, cid: CIDObject, peer_id: PeerID | None, timeout: float
    ) -> bytes:
        """
        Request a single block with WANT-HAVE → WANT-BLOCK phasing.

        Strategy:
          1. Broadcast WANT-HAVE to discover which peers have the block.
          2. Once HAVE responses arrive, send WANT-BLOCK to up to
             MAX_PARALLEL_RACE peers simultaneously (parallel racing).
          3. Take the first block response and cancel the rest.
          4. Periodically rebroadcast WANT-HAVE if no peers found yet.
        """
        logger.info(
            f"Session {self.id}: Requesting block: {format_cid_for_display(cid)}"
        )

        event = trio.Event()
        if cid not in self._pending_requests:
            self._pending_requests[cid] = set()
        self._pending_requests[cid].add(event)

        # Register with SIM
        self.client.sim.record_session_interest(self, cid)

        start_time = time.time()
        retry_interval = 1.0
        last_rebroadcast = 0.0
        requested_from: set[PeerID] = set()
        # Track peers we've sent WANT_BLOCK to (for parallel racing)
        block_requested_from: set[PeerID] = set()
        # Track peers that responded with HAVE
        have_peers: set[PeerID] = set()

        result: bytes | None = None
        error: Exception | None = None

        try:
            while time.time() - start_time < timeout:
                remaining_total = timeout - (time.time() - start_time)
                if remaining_total <= 0:
                    break

                # Phase 1: Discover peers via WANT-HAVE
                # Get peers that we know have this block
                known_have_peers = self.client.presence_manager.get_expected_peers(cid)
                untried_have_peers = known_have_peers - requested_from

                # Add any newly discovered HAVE peers
                have_peers.update(known_have_peers)

                # Check if any HAVE peers haven't been sent WANT_BLOCK yet
                untried_block_peers = have_peers - block_requested_from

                # If we have a known peer_id (from DHT), treat it as having the block
                if peer_id and peer_id not in block_requested_from:
                    have_peers.add(peer_id)
                    untried_block_peers.add(peer_id)

                if untried_block_peers and result is None:
                    # Phase 2: Send WANT-BLOCK to available peers (parallel racing)
                    targets = list(untried_block_peers)[:MAX_PARALLEL_RACE]
                    if peer_id and peer_id not in block_requested_from and peer_id in have_peers:
                        # Prioritize the specific peer if it has the block
                        if peer_id not in targets:
                            targets.insert(0, peer_id)
                            targets = targets[:MAX_PARALLEL_RACE]

                    for target in targets:
                        await self.client.want_block(
                            cid, want_type=0, send_dont_have=True
                        )
                        logger.debug(
                            f"Session {self.id}: Sending WANT-BLOCK to {target}"
                        )
                        await self.client._send_wantlist_to_peer(target, [cid])
                        block_requested_from.add(target)

                elif not have_peers:
                    # No peers known to have the block yet — broadcast WANT-HAVE
                    now = time.time()
                    should_rebroadcast = (now - last_rebroadcast) >= REBROADCAST_INTERVAL
                    untried_have = (
                        set()
                        if peer_id in requested_from
                        else ({peer_id} if peer_id else set())
                    )

                    if should_rebroadcast or untried_have:
                        await self.client.want_block(
                            cid, want_type=1, send_dont_have=True
                        )
                        logger.debug(
                            f"Session {self.id}: Broadcasting WANT-HAVE "
                            f"(rebroadcast={should_rebroadcast})"
                        )
                        await self.client._broadcast_wantlist([cid])
                        last_rebroadcast = now
                        if peer_id:
                            requested_from.add(peer_id)

                # Wait for response
                current_timeout = min(retry_interval, remaining_total)
                try:
                    with trio.fail_after(current_timeout):
                        await event.wait()

                        data = await self.client.block_store.get_block(cid)
                        if data is not None:
                            result = data
                            logger.info(
                                f"Session {self.id}: Block received! "
                                f"Size: {len(data)} bytes"
                            )
                            break
                        else:
                            # Block not in store despite event — create new event
                            # and re-register it so receive_block can set it
                            event = trio.Event()
                            self._pending_requests.setdefault(cid, set()).add(event)
                except trio.TooSlowError:
                    retry_interval = min(retry_interval * 1.5, 10.0)
                    logger.debug(
                        f"Session {self.id}: Sub-timeout reached, "
                        f"retry {retry_interval:.1f}s"
                    )

                    # Allow retrying peers after timeout
                    if peer_id and peer_id in block_requested_from:
                        block_requested_from.discard(peer_id)
                    if peer_id and peer_id in requested_from:
                        requested_from.discard(peer_id)

        except Exception as e:
            logger.error(f"Session {self.id}: Error during block request: {e}")
            error = e
        finally:
            if cid in self._pending_requests:
                self._pending_requests[cid].discard(event)
                if not self._pending_requests[cid]:
                    del self._pending_requests[cid]

            self.client.sim.remove_session_interest(self, cid)
            await self.client.cancel_want(cid)
            self.client.presence_manager.remove_dont_have(cid)
            for pid in self.client.presence_manager.get_expected_peers(cid):
                self.client.presence_manager.remove_have(pid, cid)

        if result is not None:
            return result

        if error:
            raise error

        raise BitswapTimeoutError(
            f"Timeout waiting for block {format_cid_for_display(cid, max_len=16)}"
        )

    async def get_blocks_batch(
        self,
        cids: list["CIDInput"],
        peer_id: PeerID | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        batch_size: int = 32,
    ) -> dict[bytes, bytes]:
        """
        Fetch multiple blocks in batches with WANT-HAVE phasing and parallel racing.

        Strategy per batch:
          1. Broadcast WANT-HAVE for all pending CIDs to discover providers.
          2. After HAVE responses, send WANT-BLOCK to discovered peers.
          3. Race multiple peers per CID.
          4. Periodically rebroadcast WANT-HAVE for undiscovered CIDs.
        """
        results: dict[bytes, bytes] = {}
        cid_objs = [parse_cid(c) for c in cids]

        remaining: list[CIDObject] = []
        for cid_obj in cid_objs:
            data = await self.client.block_store.get_block(cid_obj)
            if data is not None:
                results[cid_obj.buffer] = data
            else:
                remaining.append(cid_obj)

        if not remaining:
            return results

        for batch_start in range(0, len(remaining), batch_size):
            batch = remaining[batch_start : batch_start + batch_size]

            batch_events = {}
            for cid_obj in batch:
                event = trio.Event()
                if cid_obj not in self._pending_requests:
                    self._pending_requests[cid_obj] = set()
                self._pending_requests[cid_obj].add(event)
                batch_events[cid_obj] = event
                self.client.sim.record_session_interest(self, cid_obj)

            start_time = time.time()
            retry_interval = 1.0
            last_rebroadcast = 0.0
            requested_from: dict[CIDObject, set[PeerID]] = {
                cid: set() for cid in batch
            }
            block_requested_from: dict[CIDObject, set[PeerID]] = {
                cid: set() for cid in batch
            }
            have_peers: dict[CIDObject, set[PeerID]] = {cid: set() for cid in batch}

            try:
                while time.time() - start_time < timeout:
                    remaining_total = timeout - (time.time() - start_time)
                    if remaining_total <= 0:
                        break

                    still_pending = [
                        cid for cid in batch if not batch_events[cid].is_set()
                    ]
                    if not still_pending:
                        break

                    to_broadcast: list[CIDObject] = []
                    to_peer: dict[PeerID, list[CIDObject]] = {}

                    for cid in still_pending:
                        # Discover HAVE peers from presence manager
                        known_have = self.client.presence_manager.get_expected_peers(
                            cid
                        )
                        have_peers[cid].update(known_have)

                        untried_block = have_peers[cid] - block_requested_from[cid]

                        # If we have a known peer_id, treat it as having the block
                        if peer_id and peer_id not in block_requested_from[cid]:
                            have_peers[cid].add(peer_id)
                            untried_block.add(peer_id)

                        if untried_block:
                            # Send WANT-BLOCK to discovered peers (parallel racing)
                            targets = list(untried_block)[:MAX_PARALLEL_RACE]
                            if (
                                peer_id
                                and peer_id not in block_requested_from[cid]
                                and peer_id in have_peers[cid]
                            ):
                                if peer_id not in targets:
                                    targets.insert(0, peer_id)
                                    targets = targets[:MAX_PARALLEL_RACE]

                            for target in targets:
                                if target not in to_peer:
                                    to_peer[target] = []
                                to_peer[target].append(cid)
                                block_requested_from[cid].add(target)
                                self.client.peer_manager.record_request(target, cid)
                                await self.client.want_block(
                                    cid, want_type=0, send_dont_have=True
                                )
                        elif not have_peers[cid]:
                            # No HAVE peers yet — broadcast WANT-HAVE
                            now = time.time()
                            should_rebroadcast = (
                                (now - last_rebroadcast) >= REBROADCAST_INTERVAL
                            )
                            if should_rebroadcast or (
                                peer_id and peer_id not in requested_from[cid]
                            ):
                                to_broadcast.append(cid)
                                await self.client.want_block(
                                    cid, want_type=1, send_dont_have=True
                                )
                                if peer_id:
                                    requested_from[cid].add(peer_id)

                    for p, b_cids in to_peer.items():
                        logger.debug(
                            f"Session {self.id}: Batch sending WANT-BLOCK "
                            f"to {p} for {len(b_cids)} CIDs"
                        )
                        await self.client._send_wantlist_to_peer(p, b_cids)

                    if to_broadcast:
                        logger.debug(
                            f"Session {self.id}: Batch broadcasting WANT-HAVE "
                            f"for {len(to_broadcast)} CIDs"
                        )
                        await self.client._broadcast_wantlist(to_broadcast)
                        last_rebroadcast = time.time()

                    current_timeout = min(retry_interval, remaining_total)
                    try:
                        with trio.fail_after(current_timeout):
                            for cid in still_pending:
                                await batch_events[cid].wait()
                    except trio.TooSlowError:
                        retry_interval = min(retry_interval * 1.5, 10.0)

                        # Record timeouts and allow retrying
                        for cid in still_pending:
                            for req_peer in block_requested_from[cid]:
                                self.client.peer_manager.record_timeout(req_peer, cid)
                            # Allow retrying after timeout
                            block_requested_from[cid].clear()
                            requested_from[cid].clear()

                        logger.debug(
                            f"Session {self.id}: Batch sub-timeout: "
                            f"{len(still_pending)} blocks still pending, retrying..."
                        )

                for cid_obj in batch:
                    data = await self.client.block_store.get_block(cid_obj)
                    if data is not None:
                        results[cid_obj.buffer] = data
                    else:
                        cid_str = format_cid_for_display(cid_obj)
                        logger.warning(
                            f"Session {self.id}: Block not received: {cid_str}"
                        )

            finally:
                for cid_obj in batch:
                    batch_event = batch_events.get(cid_obj)
                    if batch_event is not None and cid_obj in self._pending_requests:
                        self._pending_requests[cid_obj].discard(batch_event)
                        if not self._pending_requests[cid_obj]:
                            del self._pending_requests[cid_obj]

                    self.client.sim.remove_session_interest(self, cid_obj)
                    await self.client.cancel_want(cid_obj)
                    self.client.presence_manager.remove_dont_have(cid_obj)
                    for pid in self.client.presence_manager.get_expected_peers(cid_obj):
                        self.client.presence_manager.remove_have(pid, cid_obj)

        return results

    async def receive_block(
        self, cid: CIDObject, data: bytes, peer_id: PeerID | None = None
    ) -> None:
        """Called by SIM when a block is received."""
        if peer_id:
            self.active_peers.add(peer_id)

        if cid in self._pending_requests:
            events = self._pending_requests[cid]
            logger.debug(
                f"Session {self.id}: Notifying {len(events)} requesters "
                f"for block {format_cid_for_display(cid, max_len=16)}"
            )
            for event in list(events):
                event.set()

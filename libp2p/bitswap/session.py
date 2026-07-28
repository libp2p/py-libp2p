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
    from .types import CIDInput

logger = logging.getLogger("libp2p.bitswap.session")


class BitswapSession:
    """
    A Session scopes the retrieval of a set of related blocks (like a file).
    It isolates the network state and routes requests efficiently.
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
                        cid, timeout=min(60.0, timeout * 0.8)
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
        logger.info(
            f"Session {self.id}: 📤 Requesting block: {format_cid_for_display(cid)}"
        )

        event = trio.Event()
        if cid not in self._pending_requests:
            self._pending_requests[cid] = set()
        self._pending_requests[cid].add(event)

        # Register with SIM
        self.client.sim.record_session_interest(self, cid)

        start_time = time.time()
        retry_interval = 1.0
        requested_from: set[PeerID] = set()

        result: bytes | None = None
        error: Exception | None = None
        MAX_RETRIES_PER_PEER = 3

        try:
            while time.time() - start_time < timeout:
                remaining_total = timeout - (time.time() - start_time)
                if remaining_total <= 0:
                    break

                have_peers = self.client.presence_manager.get_expected_peers(cid)
                untried_peers = have_peers - requested_from

                target_peer = None
                if peer_id and peer_id not in requested_from:
                    target_peer = peer_id
                elif untried_peers:
                    target_peer = random.choice(list(untried_peers))

                if target_peer:
                    await self.client.want_block(cid, want_type=0, send_dont_have=True)
                    logger.debug(
                        f"Session {self.id}: Sending WANT-BLOCK to {target_peer}"
                    )
                    await self.client._send_wantlist_to_peer(target_peer, [cid])
                    requested_from.add(target_peer)
                else:
                    await self.client.want_block(cid, want_type=1, send_dont_have=True)
                    logger.debug(f"Session {self.id}: Broadcasting WANT-HAVE")
                    await self.client._broadcast_wantlist([cid])

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
                            event = trio.Event()
                except trio.TooSlowError:
                    retry_interval = min(retry_interval * 1.5, 10.0)
                    logger.debug(
                        f"Session {self.id}: Sub-timeout reached, "
                        f"retry {retry_interval:.1f}s"
                    )

                    # Track retry count per peer to avoid infinite retries
                    if target_peer:
                        if not hasattr(self, '_peer_retry_counts'):
                            self._peer_retry_counts: dict = {}
                        key = (target_peer, cid)
                        count = self._peer_retry_counts.get(key, 0) + 1
                        self._peer_retry_counts[key] = count
                        if count >= MAX_RETRIES_PER_PEER:
                            requested_from.add(target_peer)
                            self._peer_retry_counts.pop(key, None)

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
        """Fetch multiple blocks in batches using a single wantlist per batch."""
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
            requested_from: dict[CIDObject, set[PeerID]] = {cid: set() for cid in batch}

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

                    to_broadcast = []
                    to_peer: dict[PeerID, list[CIDObject]] = {}

                    for cid in still_pending:
                        have_peers = self.client.presence_manager.get_expected_peers(
                            cid
                        )
                        untried = have_peers - requested_from[cid]

                        targets = []
                        if peer_id and peer_id not in requested_from[cid]:
                            targets = [peer_id]
                        elif untried:
                            targets = self.client.peer_manager.get_best_peers(
                                untried, 1
                            )
                        elif not untried and getattr(
                            self.client, "provider_query_manager", None
                        ):
                            try:
                                p_target = await (
                                    self.client.provider_query_manager
                                ).find_providers_single(cid)
                                if p_target:
                                    targets = [p_target]
                            except Exception as e:
                                logger.warning(f"PQM error for {cid}: {e}")

                        if targets:
                            for target in targets:
                                if target not in to_peer:
                                    to_peer[target] = []
                                to_peer[target].append(cid)
                                requested_from[cid].add(target)
                                self.client.peer_manager.record_request(target, cid)
                                await self.client.want_block(
                                    cid, want_type=0, send_dont_have=True
                                )
                        else:
                            to_broadcast.append(cid)
                            await self.client.want_block(
                                cid, want_type=1, send_dont_have=True
                            )

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

                    current_timeout = min(retry_interval, remaining_total)
                    try:
                        with trio.fail_after(current_timeout):
                            for cid in still_pending:
                                await batch_events[cid].wait()
                    except trio.TooSlowError:
                        retry_interval = min(retry_interval * 1.5, 10.0)

                        # Record timeouts for peers that we requested from
                        for cid in still_pending:
                            for req_peer in requested_from[cid]:
                                self.client.peer_manager.record_timeout(req_peer, cid)

                        msg = (
                            f"Session {self.id}: Batch sub-timeout: "
                            f"{len(still_pending)} blocks still pending, retrying..."
                        )
                        logger.debug(msg)

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

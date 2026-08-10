"""
Auto-connector implementation for maintaining minimum connections.

This module provides automatic connection functionality that connects to
known peers when the connection count falls below the low watermark,
matching go-libp2p behavior.

Reference: https://github.com/libp2p/go-libp2p/blob/master/p2p/net/connmgr/connmgr.go
"""

import logging
import random
import time
from typing import TYPE_CHECKING

import trio

from libp2p.network.config import AUTO_CONNECT_INTERVAL
from libp2p.peer.id import ID

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.network.auto_connector")
logger.setLevel(logging.INFO)


class AutoConnector:
    """
    Auto-connector that maintains minimum connection count.

    Periodically checks if the connection count is below the low watermark
    and attempts to connect to known peers from the peer store.

    Similar to go-libp2p's connection manager background dialer.
    """

    def __init__(
        self,
        swarm: "Swarm",
        auto_connect_interval: float = AUTO_CONNECT_INTERVAL,
    ):
        """
        Initialize the auto-connector.

        Parameters
        ----------
        swarm : Swarm
            The swarm instance for connecting
        auto_connect_interval : float
            Interval between auto-connect attempts (seconds)

        """
        self.swarm = swarm
        self.auto_connect_interval = auto_connect_interval

        self._started = False
        self._shutdown_event = trio.Event()
        self._last_connect_attempt: dict[ID, float] = {}
        self._failure_counts: dict[ID, int] = {}
        self._base_cooldown = 300.0  # base retry interval (seconds)
        self._max_cooldown = 3600.0  # cap at 1 hour for persistent failures
        # Peers that recently disconnected: we back off from immediately
        # re-dialing them (event-driven auto-connect on disconnect would
        # otherwise reconnect to the peer we just closed in a tight loop).
        self._recent_disconnects: dict[ID, float] = {}
        self._disconnect_backoff = 60.0  # seconds

    async def start(self) -> None:
        """Start the auto-connector background task."""
        self._started = True
        self._shutdown_event = trio.Event()
        logger.debug("AutoConnector started")

    async def stop(self) -> None:
        """Stop the auto-connector."""
        self._started = False
        self._shutdown_event.set()
        logger.debug("AutoConnector stopped")

    async def run_background_task(self, nursery: trio.Nursery) -> None:
        """
        Run the background task that periodically checks connection count.

        Parameters
        ----------
        nursery : trio.Nursery
            The nursery to run tasks in

        """
        if not self._started:
            return

        nursery.start_soon(self._periodic_check_task)

    async def _periodic_check_task(self) -> None:
        """Periodically check if we need to connect to more peers."""
        while self._started and not self._shutdown_event.is_set():
            try:
                await self.maybe_connect()
            except Exception as e:
                logger.error(f"Error in auto-connect: {e}", exc_info=e)

            # Wait for the next interval or shutdown
            with trio.move_on_after(self.auto_connect_interval):
                await self._shutdown_event.wait()

    async def maybe_connect(self) -> None:
        """
        Check if we should connect to more peers and do so if needed.

        Called periodically by the background task, or can be called
        manually when a peer disconnects.
        """
        if not self._started:
            return

        num_connections = self.swarm.get_total_connections()
        low_watermark = self.swarm.connection_config.low_watermark
        min_connections = self.swarm.connection_config.min_connections

        logger.info(
            "AUTO_CONNECTOR_STATE: num_connections=%s, "
            "low_watermark=%s, min_connections=%s",
            num_connections,
            low_watermark,
            min_connections,
        )

        # Only connect if below low watermark
        if num_connections >= low_watermark:
            return

        # Calculate how many connections we need
        target = low_watermark
        needed = target - num_connections

        if needed <= 0:
            return

        logger.info(
            "the connection (%s) is less the low limit (%s) "
            "so connection manager is initiating %s number of new connections",
            num_connections,
            low_watermark,
            needed,
        )

        # Get candidate peers from peerstore
        candidates = await self._get_candidate_peers()

        if not candidates:
            logger.debug("No candidate peers available for auto-connection")
            return

        # Shuffle to randomize connection order
        random.shuffle(candidates)

        # Try to connect to candidates
        # We need to limit concurrency to avoid OS "Too many open files" errors
        # (Kubo default is 160 concurrent outbound dials)
        dial_limiter = trio.CapacityLimiter(160)

        async def _dial_candidate(peer_id: ID) -> None:
            async with dial_limiter:
                connected = False
                try:
                    logger.debug(f"Auto-connecting to peer {peer_id}")
                    with trio.move_on_after(
                        self.swarm.connection_config.dial_timeout
                    ) as cancel_scope:
                        await self.swarm.dial_peer(peer_id)
                        connected = True  # only set if dial completes before timeout
                    if cancel_scope.cancelled_caught:
                        # Dial timed out — treat as failure, apply backoff
                        logger.debug(f"Dial to {peer_id} timed out")
                        self._failure_counts[peer_id] = (
                            self._failure_counts.get(peer_id, 0) + 1
                        )
                        self._last_connect_attempt[peer_id] = time.time()
                    elif connected:
                        logger.info(f"Auto-connected to peer {peer_id}")
                        # Success — clear cooldown so peer is immediately
                        # re-dialable if it disconnects later
                        self._last_connect_attempt.pop(peer_id, None)
                        self._failure_counts.pop(peer_id, None)
                except Exception as e:
                    logger.debug(f"Failed to auto-connect to {peer_id}: {e}")
                    self._failure_counts[peer_id] = (
                        self._failure_counts.get(peer_id, 0) + 1
                    )
                    self._last_connect_attempt[peer_id] = time.time()

        try:
            async with trio.open_nursery() as dial_nursery:
                dialed = 0
                # We overdial (needed * 2) because in a P2P network, most dials will
                # fail due to offline peers, NAT traversal issues, or obsolete addresses.  # noqa: E501
                dial_target = needed * 2

                for peer_id in candidates:
                    if dialed >= dial_target:
                        break

                    if self._should_skip_peer(peer_id):
                        continue

                    dial_nursery.start_soon(_dial_candidate, peer_id)
                    dialed += 1
        except Exception as e:
            logger.error(f"Error in auto_connect dial nursery: {e}")

        if dialed > 0:
            logger.info(f"Auto-connected to {dialed} new peers")

    async def _get_candidate_peers(self) -> list[ID]:
        """
        Get candidate peers for auto-connection.

        Returns peers from the peerstore that we're not currently
        connected to and have addresses available.

        Returns
        -------
        list[ID]
            List of candidate peer IDs

        """
        candidates = []

        # Get all peers from peerstore
        all_peers = self.swarm.peerstore.peer_ids()

        # Get currently connected peers
        connected_peers = set(self.swarm.connections.keys())

        for peer_id in all_peers:
            # Skip ourselves
            if peer_id == self.swarm.self_id:
                continue

            # Skip already connected peers
            if peer_id in connected_peers:
                continue

            # Check if peer has addresses
            try:
                addrs = self.swarm.peerstore.addrs(peer_id)
                if addrs:
                    candidates.append(peer_id)
            except Exception:
                continue

        return candidates

    def _get_cooldown(self, peer_id: ID) -> float:
        """
        Calculate exponential backoff cooldown for a peer.

        Returns base_cooldown * 2^(failures-1), capped at max_cooldown.
        First failure: 300s, second: 600s, third: 1200s … cap: 3600s.

        Parameters
        ----------
        peer_id : ID
            The peer to calculate cooldown for

        Returns
        -------
        float
            Cooldown duration in seconds

        """
        n = self._failure_counts.get(peer_id, 0)
        if n <= 0:
            return self._base_cooldown
        return min(self._base_cooldown * (2 ** (n - 1)), self._max_cooldown)

    def _should_skip_peer(self, peer_id: ID) -> bool:
        """
        Check if we should skip connecting to a peer.

        Skips peers that we recently tried to connect to (exponential backoff).

        Parameters
        ----------
        peer_id : ID
            The peer to check

        Returns
        -------
        bool
            True if we should skip this peer

        """
        last_attempt = self._last_connect_attempt.get(peer_id)
        if last_attempt is not None:
            if time.time() - last_attempt < self._get_cooldown(peer_id):
                return True

        # Back off recently-disconnected peers so a disconnect-triggered
        # auto-connect does not immediately re-dial the peer we just lost.
        last_disconnect = self._recent_disconnects.get(peer_id)
        if last_disconnect is not None:
            if time.time() - last_disconnect < self._disconnect_backoff:
                return True

        return False

    def record_successful_connection(self, peer_id: ID) -> None:
        """
        Record a successful connection to a peer.

        Clears the cooldown for this peer.

        Parameters
        ----------
        peer_id : ID
            The peer that we connected to

        """
        self._last_connect_attempt.pop(peer_id, None)
        self._failure_counts.pop(peer_id, None)
        self._recent_disconnects.pop(peer_id, None)

    def record_disconnect(self, peer_id: ID) -> None:
        """
        Record that a connection to a peer closed.

        The auto-connector will not attempt to re-dial this peer for
        ``_disconnect_backoff`` seconds, avoiding immediate reconnect loops
        when disconnects trigger auto-connect (Bug 6 fixup).

        Parameters
        ----------
        peer_id : ID
            The peer that disconnected

        """
        self._recent_disconnects[peer_id] = time.time()

    def record_failed_connection(self, peer_id: ID) -> None:
        """
        Record a failed connection attempt.

        Updates the last attempt time for cooldown purposes.

        Parameters
        ----------
        peer_id : ID
            The peer we failed to connect to

        """
        self._failure_counts[peer_id] = self._failure_counts.get(peer_id, 0) + 1
        self._last_connect_attempt[peer_id] = time.time()

    def clear_cooldown(self, peer_id: ID) -> None:
        """
        Clear the cooldown for a specific peer.

        Parameters
        ----------
        peer_id : ID
            The peer to clear cooldown for

        """
        self._last_connect_attempt.pop(peer_id, None)
        self._failure_counts.pop(peer_id, None)
        self._recent_disconnects.pop(peer_id, None)

    def clear_all_cooldowns(self) -> None:
        """Clear all peer cooldowns and failure counts."""
        self._last_connect_attempt.clear()
        self._failure_counts.clear()
        self._recent_disconnects.clear()

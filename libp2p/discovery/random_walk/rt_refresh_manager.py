from collections.abc import Awaitable, Callable
import logging
import time
from typing import Protocol

import trio

from libp2p.abc import IHost
from libp2p.discovery.random_walk.config import (
    RANDOM_WALK_CONCURRENCY,
    RANDOM_WALK_ENABLED,
    REFRESH_INTERVAL,
    REFRESH_TOTAL_TIMEOUT,
)
from libp2p.discovery.random_walk.exceptions import RoutingTableRefreshError
from libp2p.discovery.random_walk.random_walk import RandomWalk
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


class RoutingTableProtocol(Protocol):
    """Protocol for routing table operations needed by RT refresh manager."""

    def size(self) -> int:
        """Return the current size of the routing table."""
        ...

    async def add_peer(self, peer_obj: PeerInfo) -> bool:
        """Add a peer to the routing table."""
        ...

    def get_target_keys_for_refresh(self) -> list[bytes]:
        """Return targeted keys for each bucket in the routing table."""
        ...


logger = logging.getLogger(__name__)


class RTRefreshManager:
    """
    Routing Table Refresh Manager for py-libp2p.

    Manages periodic routing table refreshes and random walk operations
    to maintain routing table health and discover new peers.
    """

    def __init__(
        self,
        host: IHost,
        routing_table: RoutingTableProtocol,
        local_peer_id: ID,
        query_function: Callable[[bytes], Awaitable[list[ID]]],
        enable_auto_refresh: bool = RANDOM_WALK_ENABLED,
        refresh_interval: float = REFRESH_INTERVAL,
    ):
        """
        Initialize RT Refresh Manager.

        Args:
            host: The libp2p host instance
            routing_table: Routing table of host
            local_peer_id: Local peer ID
            query_function: Function to query for closest peers given target key bytes
            enable_auto_refresh: Whether to enable automatic refresh
            refresh_interval: Interval between refreshes in seconds

        """
        self.host = host
        self.routing_table = routing_table
        self.local_peer_id = local_peer_id
        self.query_function = query_function

        self.enable_auto_refresh = enable_auto_refresh
        self.refresh_interval = refresh_interval

        # Initialize random walk module
        self.random_walk = RandomWalk(
            host=host,
            local_peer_id=self.local_peer_id,
            query_function=query_function,
        )

        # Control variables
        self._running = False
        self._is_refreshing = False
        self._nursery: trio.Nursery | None = None

        # Tracking
        self._last_refresh_time = 0.0
        self._refresh_done_callbacks: list[Callable[[], None]] = []

    async def start(self) -> None:
        """Start the RT Refresh Manager."""
        if self._running:
            logger.warning("RT Refresh Manager is already running")
            return

        self._running = True

        logger.info("Starting RT Refresh Manager")

        # Start the main loop
        async with trio.open_nursery() as nursery:
            self._nursery = nursery
            nursery.start_soon(self._main_loop)

    async def stop(self) -> None:
        """Stop the RT Refresh Manager."""
        if not self._running:
            return

        logger.info("Stopping RT Refresh Manager")
        self._running = False

    async def _main_loop(self) -> None:
        """Main loop for the RT Refresh Manager."""
        logger.info("RT Refresh Manager main loop started")

        # Initial refresh if auto-refresh is enabled
        if self.enable_auto_refresh:
            await self._do_refresh(force=True)

        try:
            while self._running:
                async with trio.open_nursery() as nursery:
                    # Schedule periodic refresh if enabled
                    if self.enable_auto_refresh:
                        nursery.start_soon(self._periodic_refresh_task)

        except Exception as e:
            logger.error(f"RT Refresh Manager main loop error: {e}")
        finally:
            logger.info("RT Refresh Manager main loop stopped")

    async def trigger_refresh(self) -> None:
        """
        Manually trigger an asynchronous routing table refresh.
        Debounced so redundant triggers while a refresh is running are skipped.
        """
        if not self._running or self._is_refreshing:
            return

        logger.info("On-demand routing table refresh triggered")
        if self._nursery is not None:
            self._nursery.start_soon(self._do_refresh_safe, True)
        else:
            await self._do_refresh_safe(force=True)

    async def _do_refresh_safe(self, force: bool = False) -> None:
        """Execute refresh safely catching exceptions."""
        try:
            await self._do_refresh(force=force)
        except Exception as e:
            logger.debug(f"On-demand refresh noticed exception: {e}")

    async def _periodic_refresh_task(self) -> None:
        """Task for periodic refreshes."""
        while self._running:
            await trio.sleep(self.refresh_interval)
            if self._running:
                await self._do_refresh()

    async def _do_refresh(self, force: bool = False) -> None:
        """
        Perform routing table refresh operation.

        Args:
            force: Whether to force refresh regardless of timing

        """
        if self._is_refreshing:
            logger.debug("Routing table refresh already in progress")
            return

        try:
            self._is_refreshing = True
            current_time = time.time()

            # Check if refresh is needed
            if not force:
                if current_time - self._last_refresh_time < self.refresh_interval:
                    logger.debug("Skipping refresh: interval not elapsed")
                    return

            logger.info(f"Starting routing table refresh (force={force})")
            start_time = current_time

            # Get targeted keys from routing table buckets if available
            target_keys = None
            if hasattr(self.routing_table, "get_target_keys_for_refresh"):
                try:
                    target_keys = self.routing_table.get_target_keys_for_refresh()
                except Exception as e:
                    logger.debug(f"Failed to get targeted keys: {e}")

            logger.info("Running concurrent random walks to discover new peers")
            current_rt_size = self.routing_table.size()
            discovered_peers: list[PeerInfo] = []
            with trio.move_on_after(REFRESH_TOTAL_TIMEOUT) as _refresh_scope:
                discovered_peers = await self.random_walk.run_concurrent_random_walks(
                    count=RANDOM_WALK_CONCURRENCY,
                    current_routing_table_size=current_rt_size,
                    target_keys=target_keys,
                )
            if _refresh_scope.cancelled_caught:
                logger.debug(
                    "Random-walk batch did not complete within %.0f s; "
                    "continuing with %d peer(s) discovered so far.",
                    REFRESH_TOTAL_TIMEOUT,
                    len(discovered_peers),
                )

            # Add discovered peers to routing table
            added_count = 0
            for peer_info in discovered_peers:
                result = await self.routing_table.add_peer(peer_info)
                if result:
                    added_count += 1

            self._last_refresh_time = current_time

            duration = time.time() - start_time
            logger.info(
                f"Routing table refresh completed: "
                f"{added_count}/{len(discovered_peers)} peers added, "
                f"RT size: {self.routing_table.size()}, "
                f"duration: {duration:.2f}s"
            )

            # Post-walk connection trim: close excess connections above high-watermark
            await self._trim_walk_connections()

            # Notify refresh completion
            for callback in self._refresh_done_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.warning(f"Refresh callback error: {e}")

        except Exception as e:
            logger.error(f"Routing table refresh failed: {e}")
            raise RoutingTableRefreshError(f"Refresh operation failed: {e}") from e
        finally:
            self._is_refreshing = False

    async def _trim_walk_connections(self) -> None:
        """
        Close connections above the high-watermark after a random walk.

        The random walk may open many transient QUIC connections for DHT queries.
        Each aioquic QuicConnection holds ~5MB of crypto/buffer state.  Without
        explicit pruning they persist in memory until the 600-second idle timeout.
        With 133 dials per walk (CONCURRENCY=3) that's ~665MB retained for 10min.

        ConnectionPruner.maybe_prune_connections() sorts by: temp-entries first,
        then lowest stream-count, then inbound direction.  Auto-connector outbound
        connections are older with more stream history, so they survive pruning.
        """
        try:
            network = self.host.get_network()  # type: ignore[attr-defined]
            pruner = getattr(network, "connection_pruner", None)
            if pruner and hasattr(pruner, "maybe_prune_connections"):
                await pruner.maybe_prune_connections()
                logger.debug("Post-walk connection prune complete")
        except Exception as e:
            logger.debug("Post-walk connection prune error (non-fatal): %s", e)

    def add_refresh_done_callback(self, callback: Callable[[], None]) -> None:
        """Add a callback to be called when refresh completes."""
        self._refresh_done_callbacks.append(callback)

    def remove_refresh_done_callback(self, callback: Callable[[], None]) -> None:
        """Remove a refresh completion callback."""
        if callback in self._refresh_done_callbacks:
            self._refresh_done_callbacks.remove(callback)

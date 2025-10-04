"""
Rendezvous discovery implementation that conforms to py-libp2p's discovery interface.
"""

from collections.abc import AsyncIterator
import logging
import random
import time

import trio

from libp2p.abc import IHost
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo

from .client import RendezvousClient
from .config import (
    DEFAULT_CACHE_TTL,
    DEFAULT_DISCOVER_LIMIT,
    DEFAULT_TTL,
    MAX_DISCOVER_LIMIT,
)
from .errors import RendezvousError

logger = logging.getLogger(__name__)


class PeerCache:
    """Cache for discovered peers with TTL management."""

    def __init__(self) -> None:
        self.peers: dict[PeerID, PeerInfo] = {}
        self.expiry: dict[PeerID, float] = {}
        self.cookie: bytes = b""

    def add_peer(self, peer: PeerInfo, ttl: int) -> None:
        """Add a peer to the cache with TTL."""
        self.peers[peer.peer_id] = peer
        self.expiry[peer.peer_id] = time.time() + ttl

    def get_valid_peers(self, limit: int = 0) -> list[PeerInfo]:
        """Get valid (non-expired) peers from cache."""
        current_time = time.time()
        valid_peers = []

        # Remove expired peers
        expired = [
            peer_id
            for peer_id, exp_time in self.expiry.items()
            if exp_time < current_time
        ]
        for peer_id in expired:
            self.peers.pop(peer_id, None)
            self.expiry.pop(peer_id, None)

        # Get valid peers
        for peer in self.peers.values():
            valid_peers.append(peer)
            if limit > 0 and len(valid_peers) >= limit:
                break

        return valid_peers

    def clear(self) -> None:
        """Clear the cache."""
        self.peers.clear()
        self.expiry.clear()
        self.cookie = b""


class RendezvousDiscovery:
    """
    Rendezvous-based peer discovery.

    This class provides a high-level interface for peer discovery using
    the rendezvous protocol, including caching. Registration refresh is
    handled automatically by the underlying RendezvousClient.
    """

    def __init__(
        self, host: IHost, rendezvous_peer: PeerID, enable_refresh: bool = False
    ):
        """
        Initialize rendezvous discovery.

        Args:
            host: The libp2p host
            rendezvous_peer: Peer ID of the rendezvous server
            enable_refresh: Whether to enable automatic refresh

        """
        self.host = host
        self.client = RendezvousClient(host, rendezvous_peer, enable_refresh)
        self.caches: dict[str, PeerCache] = {}
        self._discover_locks: dict[str, trio.Lock] = {}

    async def run(self) -> None:
        """Run the rendezvous discovery service."""
        logger.info("Starting Rendezvous Discovery service")

        # Start background tasks in parallel
        async with trio.open_nursery() as nursery:
            # Set the nursery for the client's refresh tasks
            self.client.set_nursery(nursery)
            logger.info("Rendezvous Discovery service started with refresh support")

            # This will run until the nursery is cancelled
            await trio.sleep_forever()

    async def advertise(self, namespace: str, ttl: int = DEFAULT_TTL) -> float:
        """
        Advertise this peer under a namespace.

        Args:
            namespace: Namespace to advertise under
            ttl: Time-to-live in seconds (default 2 hours)

        Returns:
            Actual TTL granted by the server

        """
        return await self.client.register(namespace, ttl)

    async def find_peers(
        self,
        namespace: str,
        limit: int = DEFAULT_DISCOVER_LIMIT,
        force_refresh: bool = False,
    ) -> AsyncIterator[PeerInfo]:
        """
        Find peers in a namespace.

        Args:
            namespace: Namespace to search
            limit: Maximum number of peers to return
            force_refresh: Force refresh from server instead of using cache

        Yields:
            PeerInfo objects for discovered peers

        """
        # Get or create cache and lock for this namespace
        if namespace not in self.caches:
            self.caches[namespace] = PeerCache()
        if namespace not in self._discover_locks:
            self._discover_locks[namespace] = trio.Lock()

        cache = self.caches[namespace]
        lock = self._discover_locks[namespace]

        async with lock:
            # Try to serve from cache first
            if not force_refresh:
                cached_peers = cache.get_valid_peers(limit)
                if len(cached_peers) >= limit:
                    # Randomize order
                    random.shuffle(cached_peers)
                    for peer in cached_peers[:limit]:
                        yield peer
                    return

            # Need to discover more peers from server
            remaining_limit = limit
            if not force_refresh:
                cached_peers = cache.get_valid_peers()
                remaining_limit = max(0, limit - len(cached_peers))

            if remaining_limit > 0 or force_refresh:
                try:
                    cookie = cache.cookie if not force_refresh else b""
                    discovered_peers, new_cookie = await self.client.discover(
                        namespace, remaining_limit, cookie
                    )

                    # Add discovered peers to cache
                    # Use default cache TTL for caching
                    cache_ttl = DEFAULT_CACHE_TTL
                    for peer in discovered_peers:
                        cache.add_peer(peer, cache_ttl)

                    cache.cookie = new_cookie

                except RendezvousError as e:
                    logger.warning(f"Failed to discover peers in '{namespace}': {e}")
                    # Fall back to cached peers if discovery fails

            # Return peers from cache (now updated)
            all_peers = cache.get_valid_peers(limit)
            random.shuffle(all_peers)

            for peer in all_peers[:limit]:
                yield peer

    async def find_all_peers(self, namespace: str) -> list[PeerInfo]:
        """
        Find all peers in a namespace using pagination.

        Args:
            namespace: Namespace to search

        Returns:
            List of all discovered peers

        """
        all_peers = []
        cookie = b""

        while True:
            try:
                peers, cookie = await self.client.discover(
                    namespace, MAX_DISCOVER_LIMIT, cookie
                )
                all_peers.extend(peers)

                # If we got fewer than the limit or no cookie, we're done
                if len(peers) < MAX_DISCOVER_LIMIT or not cookie:
                    break

            except RendezvousError as e:
                logger.warning(f"Error during pagination in '{namespace}': {e}")
                break

        logger.info(f"Found {len(all_peers)} total peers in namespace '{namespace}'")
        return all_peers

    async def unregister(self, namespace: str) -> None:
        """
        Stop advertising this peer under a namespace.

        Args:
            namespace: Namespace to stop advertising under

        """
        await self.client.unregister(namespace)

        # Clear cache for this namespace
        if namespace in self.caches:
            self.caches[namespace].clear()

    def clear_cache(self, namespace: str | None = None) -> None:
        """
        Clear peer cache.

        Args:
            namespace: Specific namespace to clear, or None for all

        """
        if namespace:
            if namespace in self.caches:
                self.caches[namespace].clear()
        else:
            for cache in self.caches.values():
                cache.clear()

    async def close(self) -> None:
        """Close the discovery service and clean up resources."""
        self.caches.clear()
        self._discover_locks.clear()
        await self.client.close()

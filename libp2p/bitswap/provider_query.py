"""
Provider Query Manager for Bitswap.

This module provides DHT integration for automatic provider discovery with
caching, parallelization, and error handling. It's a critical component for
enabling automatic peer discovery in Bitswap without manual peer specification.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING

import trio

from libp2p.peer.id import ID as PeerID

from .cid import CIDInput, cid_to_bytes, format_cid_for_display

if TYPE_CHECKING:
    from libp2p.kad_dht.kad_dht import KadDHT

logger = logging.getLogger(__name__)


@dataclass
class ProviderCacheEntry:
    """
    Cached provider information for a CID.

    Attributes:
        providers: List of peer IDs that provide this content
        timestamp: When this entry was cached
        ttl: Time-to-live in seconds (how long the cache is valid)

    """

    providers: list[PeerID]
    timestamp: float = field(default_factory=time.time)
    ttl: float = 300  # 5 minutes default

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return (time.time() - self.timestamp) > self.ttl

    def age(self) -> float:
        """Get the age of this cache entry in seconds."""
        return time.time() - self.timestamp


class ProviderCache:
    """
    LRU cache for provider records with TTL support.

    Caches DHT provider query results to reduce network load and improve
    performance for repeated queries.
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300):
        """
        Initialize provider cache.

        Args:
            max_size: Maximum number of entries to cache
            default_ttl: Default time-to-live in seconds

        """
        self.max_size = max_size
        self.default_ttl: float = default_ttl
        self._cache: dict[bytes, ProviderCacheEntry] = {}
        self._access_order: list[bytes] = []  # For LRU tracking

    def get(self, cid_bytes: bytes) -> list[PeerID] | None:
        """
        Get cached providers for a CID.

        Args:
            cid_bytes: CID as bytes

        Returns:
            List of provider peer IDs if cached and not expired, None otherwise

        """
        if cid_bytes not in self._cache:
            return None

        entry = self._cache[cid_bytes]

        # Check if expired
        if entry.is_expired():
            self._remove(cid_bytes)
            return None

        # Update access order (LRU)
        self._mark_accessed(cid_bytes)

        return entry.providers

    def put(
        self,
        cid_bytes: bytes,
        providers: list[PeerID],
        ttl: float | None = None,
    ) -> None:
        """
        Cache providers for a CID.

        Args:
            cid_bytes: CID as bytes
            providers: List of provider peer IDs
            ttl: Optional custom TTL (uses default if not specified)

        """
        # Evict oldest entry if cache is full
        if len(self._cache) >= self.max_size and cid_bytes not in self._cache:
            self._evict_oldest()

        # Store entry
        entry = ProviderCacheEntry(
            providers=providers,
            timestamp=time.time(),
            ttl=ttl or self.default_ttl,
        )
        self._cache[cid_bytes] = entry
        self._mark_accessed(cid_bytes)

    def _mark_accessed(self, cid_bytes: bytes) -> None:
        """Mark a cache entry as recently accessed (for LRU)."""
        # Remove from current position if exists
        if cid_bytes in self._access_order:
            self._access_order.remove(cid_bytes)
        # Add to end (most recently used)
        self._access_order.append(cid_bytes)

    def _evict_oldest(self) -> None:
        """Evict the least recently used cache entry."""
        if not self._access_order:
            return
        oldest = self._access_order.pop(0)
        self._remove(oldest)

    def _remove(self, cid_bytes: bytes) -> None:
        """Remove an entry from the cache."""
        if cid_bytes in self._cache:
            del self._cache[cid_bytes]
        if cid_bytes in self._access_order:
            self._access_order.remove(cid_bytes)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._access_order.clear()

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries from the cache.

        Returns:
            Number of entries removed

        """
        expired = [
            cid_bytes for cid_bytes, entry in self._cache.items() if entry.is_expired()
        ]

        for cid_bytes in expired:
            self._remove(cid_bytes)

        return len(expired)

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    def stats(self) -> dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics

        """
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "expired": sum(1 for e in self._cache.values() if e.is_expired()),
        }


class ProviderQueryManager:
    """
    Manages DHT provider queries with caching and parallelization.

    This component integrates Bitswap with the Kademlia DHT to automatically
    discover which peers have specific content. It provides:

    - Automatic provider discovery via DHT
    - Parallel queries for multiple CIDs
    - Provider caching to reduce DHT load
    - Configurable limits and timeouts
    - Error handling and retry logic

    Example:
        >>> dht = KadDHT(host)
        >>> manager = ProviderQueryManager(dht)
        >>> providers = await manager.find_providers([cid1, cid2])
        >>> print(f"Found {len(providers)} provider mappings")

    """

    def __init__(
        self,
        dht: KadDHT,
        max_providers: int = 10,
        cache_ttl: float = 300,  # 5 minutes
        cache_size: int = 1000,
        max_concurrent_queries: int = 20,
    ):
        """
        Initialize Provider Query Manager.

        Args:
            dht: Kademlia DHT instance for provider queries
            max_providers: Maximum number of providers to return per CID
            cache_ttl: Cache time-to-live in seconds
            cache_size: Maximum number of CIDs to cache
            max_concurrent_queries: Maximum parallel DHT queries

        """
        self.dht = dht
        self.max_providers = max_providers
        self.cache = ProviderCache(max_size=cache_size, default_ttl=cache_ttl)
        self.query_semaphore = trio.Semaphore(max_concurrent_queries)

        # Statistics
        self._stats = {
            "queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
            "providers_found": 0,
        }

    async def find_providers(
        self,
        cids: Sequence[CIDInput],
        timeout: float = 5.0,
        use_cache: bool = True,
    ) -> dict[bytes, list[PeerID]]:
        """
        Find providers for multiple CIDs in parallel.

        This is the main entry point for provider discovery. It:
        1. Checks cache for each CID
        2. Queries DHT in parallel for cache misses
        3. Updates cache with results
        4. Returns combined results

        Args:
            cids: List of CIDs to find providers for
            timeout: Timeout per DHT query in seconds
            use_cache: Whether to use cached results

        Returns:
            Dictionary mapping CID bytes to list of provider peer IDs

        Example:
            >>> cids = [cid1, cid2, cid3]
            >>> results = await manager.find_providers(cids)
            >>> for cid_bytes, providers in results.items():
            ...     n = len(providers)
            ...     print(f"CID {cid_bytes.hex()[:8]}... has {n} providers")

        """
        results: dict[bytes, list[PeerID]] = {}
        missing: list[tuple[CIDInput, bytes]] = []

        # Phase 1: Check cache
        for cid in cids:
            cid_bytes = cid_to_bytes(cid)

            if use_cache:
                cached = self.cache.get(cid_bytes)
                if cached is not None:
                    results[cid_bytes] = cached
                    self._stats["cache_hits"] += 1
                    logger.debug(
                        f"Cache hit for {format_cid_for_display(cid, max_len=12)}: "
                        f"{len(cached)} providers"
                    )
                    continue

            # Not in cache or cache disabled
            missing.append((cid, cid_bytes))
            self._stats["cache_misses"] += 1

        if not missing:
            logger.debug(f"All {len(cids)} CIDs found in cache")
            return results

        logger.info(
            f"Querying DHT for {len(missing)} CIDs (cache hits: {len(results)})"
        )

        # Phase 2: Query DHT in parallel for missing CIDs
        async with trio.open_nursery() as nursery:
            for cid, cid_bytes in missing:
                nursery.start_soon(
                    self._query_single,
                    cid,
                    cid_bytes,
                    results,
                    timeout,
                )

        logger.info(
            f"Provider discovery complete: {len(results)}/{len(cids)} CIDs resolved"
        )

        return results

    async def _query_single(
        self,
        cid: CIDInput,
        cid_bytes: bytes,
        results: dict[bytes, list[PeerID]],
        timeout: float,
    ) -> None:
        """
        Query DHT for providers of a single CID.

        This method is called concurrently for each CID. It uses a semaphore
        to limit parallelism and handles errors gracefully.

        Args:
            cid: CID to query (for display)
            cid_bytes: CID as bytes (for DHT query)
            results: Shared results dictionary to update
            timeout: Query timeout in seconds

        """
        async with self.query_semaphore:
            self._stats["queries"] += 1

            try:
                with trio.fail_after(timeout):
                    # Query DHT provider store
                    provider_infos = self.dht.provider_store.get_providers(cid_bytes)

                    # Extract peer IDs from PeerInfo objects
                    providers = [info.peer_id for info in provider_infos]

                    # Limit to max_providers
                    if len(providers) > self.max_providers:
                        providers = providers[: self.max_providers]

                    if providers:
                        # Update results
                        results[cid_bytes] = providers

                        # Update cache
                        self.cache.put(cid_bytes, providers)

                        # Update stats
                        self._stats["providers_found"] += len(providers)

                        logger.debug(
                            f"Found {len(providers)} providers for "
                            f"{format_cid_for_display(cid, max_len=12)}"
                        )
                    else:
                        logger.debug(
                            f"No providers found for "
                            f"{format_cid_for_display(cid, max_len=12)}"
                        )

            except trio.TooSlowError:
                self._stats["errors"] += 1
                logger.warning(
                    f"DHT query timeout for {format_cid_for_display(cid, max_len=12)}"
                )
            except Exception as e:
                self._stats["errors"] += 1
                cid_disp = format_cid_for_display(cid, max_len=12)
                logger.error(f"DHT query error for {cid_disp}: {e}")

    async def find_providers_single(
        self,
        cid: CIDInput,
        timeout: float = 5.0,
        use_cache: bool = True,
    ) -> list[PeerID]:
        """
        Find providers for a single CID (convenience method).

        Args:
            cid: CID to find providers for
            timeout: Query timeout in seconds
            use_cache: Whether to use cached results

        Returns:
            List of provider peer IDs

        Example:
            >>> providers = await manager.find_providers_single(cid)
            >>> for peer_id in providers:
            ...     print(f"Provider: {peer_id}")

        """
        results = await self.find_providers([cid], timeout, use_cache)
        cid_bytes = cid_to_bytes(cid)
        return results.get(cid_bytes, [])

    def get_stats(self) -> dict[str, int]:
        """
        Get provider query statistics.

        Returns:
            Dictionary with statistics:
            - queries: Total DHT queries made
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - errors: Number of query errors
            - providers_found: Total providers discovered
            - cache_size: Current cache size

        Example:
            >>> stats = manager.get_stats()
            >>> print(f"Cache hit rate: {stats['cache_hits'] / stats['queries']:.1%}")

        """
        stats = self._stats.copy()
        stats.update(self.cache.stats())
        return stats

    def clear_cache(self) -> None:
        """Clear the provider cache."""
        self.cache.clear()
        logger.info("Provider cache cleared")

    async def cleanup_expired_cache(self) -> int:
        """
        Remove expired entries from cache.

        Returns:
            Number of entries removed

        """
        removed = self.cache.cleanup_expired()
        if removed > 0:
            logger.debug(f"Removed {removed} expired cache entries")
        return removed

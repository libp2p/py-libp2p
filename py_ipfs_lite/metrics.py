from typing import Any

from prometheus_client import Counter, Gauge, Histogram

IPFS_BLOCKSTORE_SIZE_BYTES = Gauge(
    "ipfs_blockstore_size_bytes", "Total size of blocks in the blockstore"
)

IPFS_BLOCKSTORE_BLOCKS_TOTAL = Gauge(
    "ipfs_blockstore_blocks_total", "Total number of blocks in the blockstore"
)

IPFS_BITSWAP_BYTES_SENT_TOTAL = Counter(
    "ipfs_bitswap_bytes_sent_total", "Total bytes sent over bitswap"
)

IPFS_BITSWAP_BYTES_RECEIVED_TOTAL = Counter(
    "ipfs_bitswap_bytes_received_total", "Total bytes received over bitswap"
)

IPFS_DHT_QUERY_LATENCY_SECONDS = Histogram(
    "ipfs_dht_query_latency_seconds", "Latency of DHT queries"
)

IPFS_GC_RUNS_TOTAL = Counter(
    "ipfs_gc_runs_total", "Total number of garbage collection runs"
)

IPFS_GC_RECLAIMED_BLOCKS_TOTAL = Counter(
    "ipfs_gc_reclaimed_blocks_total",
    "Total number of blocks reclaimed during garbage collection",
)

IPFS_SWARM_PEERS = Gauge("ipfs_swarm_peers", "Number of connected swarm peers")


class MetricsBlockStore:
    """Wraps a libp2p BlockStore to record prometheus metrics on put/delete."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def put_block(self, cid: bytes, data: bytes) -> None:
        await self._store.put_block(cid, data)
        IPFS_BLOCKSTORE_BLOCKS_TOTAL.inc()
        IPFS_BLOCKSTORE_SIZE_BYTES.inc(len(data))

    async def put_many(self, blocks: Any) -> None:
        if hasattr(self._store, "put_many"):
            await self._store.put_many(blocks)
        else:
            for cid, data in blocks:
                await self.put_block(cid, data)

    async def get_block(self, cid: bytes) -> Any:
        return await self._store.get_block(cid)

    async def has_block(self, cid: bytes) -> bool:
        return await self._store.has_block(cid)

    async def delete_block(self, cid: bytes) -> None:
        size = 0
        try:
            size = await self.get_size(cid)
        except Exception:
            pass

        await self._store.delete_block(cid)

        try:
            IPFS_BLOCKSTORE_BLOCKS_TOTAL.dec()
            if size > 0:
                IPFS_BLOCKSTORE_SIZE_BYTES.dec(size)
        except Exception:
            pass

    async def get_size(self, cid: bytes) -> int:
        if hasattr(self._store, "get_size"):
            import inspect

            if inspect.iscoroutinefunction(self._store.get_size):
                return await self._store.get_size(cid)
            return self._store.get_size(cid)
        data = await self.get_block(cid)
        return len(data) if data else 0

    def get_all_cids(self) -> Any:
        return self._store.get_all_cids()

    def __getattr__(self, name: Any) -> Any:
        return getattr(self._store, name)

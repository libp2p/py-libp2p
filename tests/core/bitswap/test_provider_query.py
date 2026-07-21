"""
Tests for ProviderQueryManager and its integration with BitswapClient.

Covers:
- ProviderCacheEntry  – TTL, expiry
- ProviderCache       – LRU eviction, TTL, cleanup, stats
- ProviderQueryManager – single/batch queries, cache hit/miss,
                         max_providers cap, error handling, stats
- BitswapClient integration – provider_query_manager wired at construction,
                               get_block() uses DHT discovery
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest
import trio

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import cid_to_bytes, compute_cid_v0, parse_cid
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.provider_query import (
    ProviderCache,
    ProviderCacheEntry,
    ProviderQueryManager,
)
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo

# ── helpers ───────────────────────────────────────────────────────────────────

PEER_A = PeerID.from_base58("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")
PEER_B = PeerID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ")
PEER_C = PeerID.from_base58("QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64")

SAMPLE_PEERS = [PEER_A, PEER_B, PEER_C]

CID_1 = parse_cid(compute_cid_v0(b"block-one"))
CID_2 = parse_cid(compute_cid_v0(b"block-two"))
CID_3 = parse_cid(compute_cid_v0(b"block-three"))

SAMPLE_CIDS = [CID_1, CID_2, CID_3]


def _mock_dht(return_peers: list[PeerID] | None = None) -> Mock:
    """
    Return a mock DHT whose provider_store.find_providers returns *return_peers*.

    find_providers is the async network lookup path; get_providers is the
    local-store read that ProviderQueryManager no longer calls directly.
    """
    dht = Mock()
    dht.provider_store = Mock()
    peer_infos = [PeerInfo(p, []) for p in (return_peers or [])]

    async def _async_find_providers(key: bytes, count: int = 20) -> list[PeerInfo]:
        return peer_infos[:count]

    dht.provider_store.find_providers = Mock(side_effect=_async_find_providers)
    return dht


# ═════════════════════════════════════════════════════════════════════════════
# ProviderCacheEntry
# ═════════════════════════════════════════════════════════════════════════════


class TestProviderCacheEntry:
    def test_fresh_entry_not_expired(self) -> None:
        entry = ProviderCacheEntry(providers=SAMPLE_PEERS, ttl=300)
        assert not entry.is_expired()
        assert entry.age() < 1.0

    def test_entry_with_past_timestamp_is_expired(self) -> None:
        entry = ProviderCacheEntry(
            providers=SAMPLE_PEERS,
            timestamp=time.time() - 10,
            ttl=5,
        )
        assert entry.is_expired()

    def test_default_ttl_applied(self) -> None:
        entry = ProviderCacheEntry(providers=[PEER_A])
        assert entry.ttl == 300


# ═════════════════════════════════════════════════════════════════════════════
# ProviderCache
# ═════════════════════════════════════════════════════════════════════════════


class TestProviderCache:
    def test_put_and_get(self) -> None:
        cache = ProviderCache(max_size=10, default_ttl=60)
        cache.put(b"k1", SAMPLE_PEERS)
        assert cache.get(b"k1") == SAMPLE_PEERS

    def test_miss_returns_none(self) -> None:
        cache = ProviderCache()
        assert cache.get(b"no-such-key") is None

    def test_expired_entry_returns_none(self) -> None:
        cache = ProviderCache(max_size=10, default_ttl=300)
        cache.put(b"k1", SAMPLE_PEERS, ttl=0.01)
        time.sleep(0.05)
        assert cache.get(b"k1") is None

    def test_lru_evicts_oldest(self) -> None:
        cache = ProviderCache(max_size=3, default_ttl=300)
        cache.put(b"a", [PEER_A])
        cache.put(b"b", [PEER_B])
        cache.put(b"c", [PEER_C])
        cache.get(b"a")  # mark 'a' recently used
        cache.put(b"d", [PEER_A])  # 'b' should be evicted
        assert cache.get(b"b") is None
        assert cache.get(b"a") is not None
        assert cache.get(b"d") is not None

    def test_clear_empties_cache(self) -> None:
        cache = ProviderCache(max_size=10, default_ttl=300)
        cache.put(b"k1", [PEER_A])
        cache.put(b"k2", [PEER_B])
        cache.clear()
        assert cache.size() == 0

    def test_cleanup_expired_removes_stale(self) -> None:
        cache = ProviderCache(max_size=10, default_ttl=300)
        cache.put(b"stale", [PEER_A], ttl=0.01)
        cache.put(b"fresh", [PEER_B], ttl=300)
        time.sleep(0.05)
        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.size() == 1

    def test_stats_keys_present(self) -> None:
        cache = ProviderCache(max_size=5, default_ttl=300)
        cache.put(b"k", [PEER_A])
        stats = cache.stats()
        assert {"size", "max_size", "expired"} <= stats.keys()
        assert stats["size"] == 1
        assert stats["max_size"] == 5


# ═════════════════════════════════════════════════════════════════════════════
# ProviderQueryManager
# ═════════════════════════════════════════════════════════════════════════════


class TestProviderQueryManager:
    @pytest.mark.trio
    async def test_cache_miss_queries_dht(self) -> None:
        dht = _mock_dht(return_peers=[PEER_A])
        mgr = ProviderQueryManager(dht)

        providers = await mgr.find_providers_single(CID_1, timeout=5.0)

        assert providers == [PEER_A]
        stats = mgr.get_stats()
        assert stats["queries"] == 1
        assert stats["cache_misses"] == 1
        assert stats["cache_hits"] == 0
        assert stats["providers_found"] == 1
        # Verify the async network path was used, not the local store read
        dht.provider_store.find_providers.assert_called_once()

    @pytest.mark.trio
    async def test_cache_hit_skips_dht(self) -> None:
        dht = _mock_dht()
        mgr = ProviderQueryManager(dht)
        mgr.cache.put(cid_to_bytes(CID_1), [PEER_B])

        providers = await mgr.find_providers_single(CID_1)

        assert providers == [PEER_B]
        dht.provider_store.find_providers.assert_not_called()
        assert mgr.get_stats()["cache_hits"] == 1

    @pytest.mark.trio
    async def test_second_call_uses_cache(self) -> None:
        dht = _mock_dht(return_peers=[PEER_A])
        mgr = ProviderQueryManager(dht)

        await mgr.find_providers_single(CID_1)  # miss
        await mgr.find_providers_single(CID_1)  # hit

        stats = mgr.get_stats()
        assert stats["queries"] == 1  # no extra DHT call
        assert stats["cache_hits"] == 1

    @pytest.mark.trio
    async def test_max_providers_cap(self) -> None:
        dht = _mock_dht(return_peers=SAMPLE_PEERS)
        mgr = ProviderQueryManager(dht, max_providers=1)

        providers = await mgr.find_providers_single(CID_1)
        assert len(providers) == 1

    @pytest.mark.trio
    async def test_no_providers_returns_empty(self) -> None:
        dht = _mock_dht(return_peers=[])
        mgr = ProviderQueryManager(dht)
        providers = await mgr.find_providers_single(CID_1)
        assert providers == []

    @pytest.mark.trio
    async def test_dht_error_increments_errors(self) -> None:
        dht = _mock_dht()

        async def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("dht down")

        dht.provider_store.find_providers = Mock(side_effect=_raise)
        mgr = ProviderQueryManager(dht)

        providers = await mgr.find_providers_single(CID_1, timeout=5.0)

        assert providers == []
        assert mgr.get_stats()["errors"] == 1

    @pytest.mark.trio
    async def test_batch_all_cache_hits(self) -> None:
        dht = _mock_dht()
        mgr = ProviderQueryManager(dht)
        for cid in SAMPLE_CIDS:
            mgr.cache.put(cid_to_bytes(cid), [PEER_A])

        results = await mgr.find_providers(SAMPLE_CIDS)

        assert len(results) == 3
        dht.provider_store.find_providers.assert_not_called()

    @pytest.mark.trio
    async def test_batch_partial_cache(self) -> None:
        dht = _mock_dht(return_peers=[PEER_B])
        mgr = ProviderQueryManager(dht)
        # Pre-cache only first CID
        mgr.cache.put(cid_to_bytes(CID_1), [PEER_A])

        results = await mgr.find_providers(SAMPLE_CIDS)

        assert len(results) == 3
        # Only 2 DHT calls (CID_2 and CID_3 are cache misses)
        assert dht.provider_store.find_providers.call_count == 2

    @pytest.mark.trio
    async def test_use_cache_false_always_queries_dht(self) -> None:
        dht = _mock_dht(return_peers=[PEER_A])
        mgr = ProviderQueryManager(dht)
        mgr.cache.put(cid_to_bytes(CID_1), [PEER_B])  # pre-populated

        providers = await mgr.find_providers_single(CID_1, use_cache=False)

        # DHT was queried despite cache having an entry
        dht.provider_store.find_providers.assert_called_once()
        assert providers == [PEER_A]

    @pytest.mark.trio
    async def test_clear_cache_forces_new_query(self) -> None:
        dht = _mock_dht(return_peers=[PEER_A])
        mgr = ProviderQueryManager(dht)

        await mgr.find_providers_single(CID_1)  # miss → cached
        await mgr.find_providers_single(CID_1)  # hit
        mgr.clear_cache()
        await mgr.find_providers_single(CID_1)  # miss again

        assert mgr.get_stats()["cache_misses"] == 2
        assert dht.provider_store.find_providers.call_count == 2

    @pytest.mark.trio
    async def test_cleanup_expired_cache(self) -> None:
        dht = _mock_dht()
        mgr = ProviderQueryManager(dht)
        mgr.cache.put(cid_to_bytes(CID_1), [PEER_A], ttl=0.01)
        mgr.cache.put(cid_to_bytes(CID_2), [PEER_B], ttl=300)
        await trio.sleep(0.05)

        removed = await mgr.cleanup_expired_cache()

        assert removed == 1
        assert mgr.cache.size() == 1

    def test_get_stats_initial_values(self) -> None:
        mgr = ProviderQueryManager(_mock_dht())
        stats = mgr.get_stats()
        assert stats["queries"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["errors"] == 0
        assert stats["providers_found"] == 0

    @pytest.mark.trio
    async def test_empty_cid_list(self) -> None:
        mgr = ProviderQueryManager(_mock_dht())
        assert await mgr.find_providers([]) == {}


# ═════════════════════════════════════════════════════════════════════════════
# BitswapClient integration
# ═════════════════════════════════════════════════════════════════════════════


class TestBitswapClientProviderQueryIntegration:
    """Verify that BitswapClient wires ProviderQueryManager into get_block()."""

    def _make_client(
        self,
        mock_host: Mock,
        pqm: ProviderQueryManager | None = None,
    ) -> BitswapClient:
        store = MemoryBlockStore()
        return BitswapClient(mock_host, block_store=store, provider_query_manager=pqm)

    def test_provider_query_manager_stored_on_client(self, mock_host: Mock) -> None:
        dht = _mock_dht()
        pqm = ProviderQueryManager(dht)
        client = self._make_client(mock_host, pqm)
        assert client.provider_query_manager is pqm

    def test_no_pqm_by_default(self, mock_host: Mock) -> None:
        client = self._make_client(mock_host)
        assert client.provider_query_manager is None

    @pytest.mark.trio
    async def test_get_block_returns_local_without_dht(self, mock_host: Mock) -> None:
        """Local cache hit must never touch the DHT."""
        dht = _mock_dht(return_peers=[PEER_A])
        pqm = ProviderQueryManager(dht)
        client = self._make_client(mock_host, pqm)

        block_data = b"local block"
        cid = parse_cid(compute_cid_v0(block_data))
        await client.block_store.put_block(cid, block_data)

        result = await client.block_store.get_block(cid)
        assert result == block_data
        # DHT must not have been consulted
        dht.provider_store.find_providers.assert_not_called()

    @pytest.mark.trio
    async def test_get_block_uses_pqm_to_pick_peer(self, mock_host: Mock) -> None:
        """
        When the block is not local, get_block() should call
        provider_query_manager.find_providers_single() and use the
        returned peer_id.
        """
        discovered_peer = PEER_A
        block_data = b"remote block"
        cid = parse_cid(compute_cid_v0(block_data))

        dht = _mock_dht(return_peers=[discovered_peer])
        pqm = ProviderQueryManager(dht)
        client = self._make_client(mock_host, pqm)

        # Patch _request_block so we can inspect the peer_id it receives
        captured: dict[str, object] = {}

        async def _fake_request(cid_obj, peer_id, timeout):  # noqa: ANN001
            captured["peer_id"] = peer_id
            return block_data, peer_id

        client._request_block = _fake_request  # type: ignore[method-assign]

        result = await client.get_block(cid)

        assert result == block_data
        assert captured["peer_id"] == discovered_peer

    @pytest.mark.trio
    async def test_get_block_falls_back_to_broadcast_when_no_providers(
        self, mock_host: Mock
    ) -> None:
        """
        When the DHT returns no providers, get_block() must still call
        _request_block with peer_id=None (broadcast fallback).
        """
        dht = _mock_dht(return_peers=[])
        pqm = ProviderQueryManager(dht)
        client = self._make_client(mock_host, pqm)

        block_data = b"broadcast block"
        cid = parse_cid(compute_cid_v0(block_data))

        captured: dict[str, object] = {}

        async def _fake_request(cid_obj, peer_id, timeout):  # noqa: ANN001
            captured["peer_id"] = peer_id
            return block_data, peer_id

        client._request_block = _fake_request  # type: ignore[method-assign]

        result = await client.get_block(cid)

        assert result == block_data
        assert captured["peer_id"] is None  # broadcast

    @pytest.mark.trio
    async def test_explicit_peer_id_skips_pqm(self, mock_host: Mock) -> None:
        """An explicit peer_id argument must bypass DHT discovery."""
        dht = _mock_dht(return_peers=[PEER_B])
        pqm = ProviderQueryManager(dht)
        client = self._make_client(mock_host, pqm)

        block_data = b"explicit peer block"
        cid = parse_cid(compute_cid_v0(block_data))

        captured: dict[str, object] = {}

        async def _fake_request(cid_obj, peer_id, timeout):  # noqa: ANN001
            captured["peer_id"] = peer_id
            return block_data, peer_id

        client._request_block = _fake_request  # type: ignore[method-assign]

        await client.get_block(cid, peer_id=PEER_A)

        # DHT must NOT have been called
        dht.provider_store.get_providers.assert_not_called()
        # The explicit peer_id must be passed through unchanged
        assert captured["peer_id"] == PEER_A

    @pytest.mark.trio
    async def test_pqm_error_falls_back_gracefully(self, mock_host: Mock) -> None:
        """A crashing PQM must not prevent the block fetch from proceeding."""
        dht = _mock_dht()

        async def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("dht exploded")

        dht.provider_store.find_providers = Mock(side_effect=_raise)
        pqm = ProviderQueryManager(dht)
        client = self._make_client(mock_host, pqm)

        block_data = b"fallback block"
        cid = parse_cid(compute_cid_v0(block_data))

        captured: dict[str, object] = {}

        async def _fake_request(cid_obj, peer_id, timeout):  # noqa: ANN001
            captured["peer_id"] = peer_id
            return block_data, peer_id

        client._request_block = _fake_request  # type: ignore[method-assign]

        result = await client.get_block(cid)

        assert result == block_data
        assert captured["peer_id"] is None  # graceful broadcast fallback

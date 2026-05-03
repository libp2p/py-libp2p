"""
Test BlockService — transparent local→network fallback with auto-caching.

Run with:
    python test_block_service.py
"""
import trio
from unittest.mock import AsyncMock, MagicMock, call

from libp2p.bitswap.block_service import BlockService
from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import compute_cid_v1, CODEC_RAW, cid_to_text
from libp2p.bitswap.client import BitswapClient


def make_block(content: bytes):
    cid = compute_cid_v1(content, codec=CODEC_RAW)
    return cid, content


def ok(label): print(f"  OK  {label}")


# ── helpers ───────────────────────────────────────────────────────────────────

def make_service(network_blocks: dict = None):
    """
    Build a BlockService with a real MemoryBlockStore and a mock BitswapClient.
    network_blocks: cid_bytes -> data that the mock 'network' can return.
    """
    store = MemoryBlockStore()
    mock_bitswap = MagicMock(spec=BitswapClient)
    mock_bitswap.block_store = store
    network_blocks = network_blocks or {}

    async def fake_get_block(cid, peer_id=None, timeout=30.0):
        return network_blocks.get(bytes(cid))

    async def fake_add_block(cid, data):
        pass  # just accept it

    async def fake_get_blocks_batch(cids, peer_id=None, timeout=30.0, batch_size=32):
        return {bytes(c): network_blocks[bytes(c)]
                for c in cids if bytes(c) in network_blocks}

    mock_bitswap.get_block = AsyncMock(side_effect=fake_get_block)
    mock_bitswap.add_block = AsyncMock(side_effect=fake_add_block)
    mock_bitswap.get_blocks_batch = AsyncMock(side_effect=fake_get_blocks_batch)

    service = BlockService(store, mock_bitswap)
    return service, store, mock_bitswap


# ── tests ─────────────────────────────────────────────────────────────────────

async def test_local_hit_no_network():
    print("\n[1] Local hit — network is never called")
    cid, data = make_block(b"already stored locally")
    service, store, mock_bitswap = make_service()

    # Pre-populate local store
    await store.put_block(cid, data)

    result = await service.get_block(cid)
    assert result == data
    ok("get_block returns local data")

    mock_bitswap.get_block.assert_not_called()
    ok("network (bitswap.get_block) was NOT called")


async def test_local_miss_goes_to_network():
    print("\n[2] Local miss — fetches from network")
    cid, data = make_block(b"only on the network")
    service, store, mock_bitswap = make_service(network_blocks={bytes(cid): data})

    result = await service.get_block(cid)
    assert result == data
    ok("get_block returns network data")

    mock_bitswap.get_block.assert_called_once()
    ok("network (bitswap.get_block) was called exactly once")


async def test_auto_cache_after_network_fetch():
    print("\n[3] Auto-cache — network-fetched block stored locally")
    cid, data = make_block(b"fetch and cache me")
    service, store, mock_bitswap = make_service(network_blocks={bytes(cid): data})

    # First call: local miss → network fetch → auto-cache
    result1 = await service.get_block(cid)
    assert result1 == data

    # Verify it's now in the local store
    cached = await store.get_block(cid)
    assert cached == data
    ok("block is in local store after first network fetch")

    # Second call: must be a local hit, no second network call
    result2 = await service.get_block(cid)
    assert result2 == data
    assert mock_bitswap.get_block.call_count == 1  # still only 1 network call
    ok("second get_block is a local hit (network called only once total)")


async def test_put_block_stores_and_announces():
    print("\n[4] put_block — stores locally AND calls bitswap.add_block")
    cid, data = make_block(b"new block to store")
    service, store, mock_bitswap = make_service()

    await service.put_block(cid, data)

    # Must be in local store
    cached = await store.get_block(cid)
    assert cached == data
    ok("block is in local store after put_block")

    # Must have called bitswap.add_block (announces to waiting peers)
    mock_bitswap.add_block.assert_called_once()
    ok("bitswap.add_block was called (peers notified)")


async def test_get_blocks_batch_local_hits_skip_network():
    print("\n[5] get_blocks_batch — local hits skip network")
    blocks = [make_block(f"block {i}".encode()) for i in range(5)]
    service, store, mock_bitswap = make_service()

    # Store all 5 locally
    for cid, data in blocks:
        await store.put_block(cid, data)

    cids = [cid for cid, _ in blocks]
    results = await service.get_blocks_batch(cids)

    assert len(results) == 5
    ok("all 5 blocks returned from local store")
    mock_bitswap.get_blocks_batch.assert_not_called()
    ok("network batch fetch was NOT called")


async def test_get_blocks_batch_partial_local():
    print("\n[6] get_blocks_batch — partial local, rest from network")
    local_blocks = [make_block(f"local {i}".encode()) for i in range(3)]
    net_blocks   = [make_block(f"remote {i}".encode()) for i in range(2)]
    network_dict = {bytes(cid): data for cid, data in net_blocks}

    service, store, mock_bitswap = make_service(network_blocks=network_dict)

    # Store only local blocks
    for cid, data in local_blocks:
        await store.put_block(cid, data)

    all_cids = [cid for cid, _ in local_blocks + net_blocks]
    results = await service.get_blocks_batch(all_cids)

    assert len(results) == 5
    ok("all 5 blocks returned (3 local + 2 network)")
    mock_bitswap.get_blocks_batch.assert_called_once()
    ok("network batch fetch called exactly once (only for 2 missing blocks)")

    # Network blocks must now be cached locally
    for cid, data in net_blocks:
        cached = await store.get_block(cid)
        assert cached == data
    ok("network-fetched blocks are now cached locally")


async def test_missing_block_returns_none():
    print("\n[7] get_block returns None when block not found anywhere")
    cid, _ = make_block(b"this block does not exist")
    service, store, mock_bitswap = make_service(network_blocks={})  # empty network

    result = await service.get_block(cid)
    assert result is None
    ok("get_block returns None for unknown block")


async def test_merkledag_uses_block_service():
    print("\n[8] MerkleDag.add_bytes routes through BlockService")
    from libp2p.bitswap.dag import MerkleDag
    from libp2p.bitswap.dag_pb import is_file_node

    service, store, mock_bitswap = make_service()
    dag = MerkleDag(mock_bitswap, block_service=service)

    data = b"hello block service" * 100
    root_cid = await dag.add_bytes(data)

    # All blocks must be in the local store via BlockService
    cached = await store.get_block(root_cid)
    assert cached is not None
    ok("root block is in local store via BlockService")

    # bitswap.add_block was called (for peer announcement)
    assert mock_bitswap.add_block.called
    ok("bitswap.add_block was called for peer announcement")

    # MerkleDag without BlockService still works (no regression)
    service2, store2, mock_bitswap2 = make_service()
    dag2 = MerkleDag(mock_bitswap2)  # no block_service
    root_cid2 = await dag2.add_bytes(data)
    assert root_cid2 is not None
    ok("MerkleDag without BlockService still works (no regression)")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("BlockService — Test Suite")
    print("=" * 60)

    await test_local_hit_no_network()
    await test_local_miss_goes_to_network()
    await test_auto_cache_after_network_fetch()
    await test_put_block_stores_and_announces()
    await test_get_blocks_batch_local_hits_skip_network()
    await test_get_blocks_batch_partial_local()
    await test_missing_block_returns_none()
    await test_merkledag_uses_block_service()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    trio.run(main)

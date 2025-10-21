"""Unit tests for block store implementations."""

import pytest

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import compute_cid_v1


class TestMemoryBlockStore:
    """Test MemoryBlockStore implementation."""

    @pytest.mark.trio
    async def test_init_empty(self):
        """Test initializing an empty block store."""
        store = MemoryBlockStore()
        cids = store.get_all_cids()
        assert len(cids) == 0

    @pytest.mark.trio
    async def test_put_and_get_block(self):
        """Test storing and retrieving a block."""
        store = MemoryBlockStore()
        data = b"test data"
        cid = compute_cid_v1(data)

        # Put block
        await store.put_block(cid, data)

        # Get block
        retrieved = await store.get_block(cid)
        assert retrieved == data

    @pytest.mark.trio
    async def test_get_nonexistent_block(self):
        """Test getting a block that doesn't exist."""
        store = MemoryBlockStore()
        cid = compute_cid_v1(b"nonexistent")

        result = await store.get_block(cid)
        assert result is None

    @pytest.mark.trio
    async def test_has_block(self):
        """Test checking if block exists."""
        store = MemoryBlockStore()
        data = b"test data"
        cid = compute_cid_v1(data)

        # Should not have block initially
        assert not await store.has_block(cid)

        # Put block
        await store.put_block(cid, data)

        # Should have block now
        assert await store.has_block(cid)

    @pytest.mark.trio
    async def test_delete_block(self):
        """Test deleting a block."""
        store = MemoryBlockStore()
        data = b"test data"
        cid = compute_cid_v1(data)

        # Put block
        await store.put_block(cid, data)
        assert await store.has_block(cid)

        # Delete block
        await store.delete_block(cid)
        assert not await store.has_block(cid)

    @pytest.mark.trio
    async def test_delete_nonexistent_block(self):
        """Test deleting a block that doesn't exist (should not raise)."""
        store = MemoryBlockStore()
        cid = compute_cid_v1(b"nonexistent")

        # Should not raise
        await store.delete_block(cid)

    @pytest.mark.trio
    async def test_get_all_cids(self):
        """Test getting all CIDs in the store."""
        store = MemoryBlockStore()
        data1 = b"data1"
        data2 = b"data2"
        data3 = b"data3"

        cid1 = compute_cid_v1(data1)
        cid2 = compute_cid_v1(data2)
        cid3 = compute_cid_v1(data3)

        # Put blocks
        await store.put_block(cid1, data1)
        await store.put_block(cid2, data2)
        await store.put_block(cid3, data3)

        # Get all CIDs
        cids = store.get_all_cids()
        assert len(cids) == 3
        assert cid1 in cids
        assert cid2 in cids
        assert cid3 in cids

    @pytest.mark.trio
    async def test_put_duplicate_block(self):
        """Test putting the same block twice."""
        store = MemoryBlockStore()
        data = b"test data"
        cid = compute_cid_v1(data)

        # Put block twice
        await store.put_block(cid, data)
        await store.put_block(cid, data)

        # Should only have one copy
        cids = store.get_all_cids()
        assert len(cids) == 1
        assert cid in cids

    @pytest.mark.trio
    async def test_multiple_blocks(self):
        """Test storing multiple different blocks."""
        store = MemoryBlockStore()
        blocks = {
            compute_cid_v1(b"data1"): b"data1",
            compute_cid_v1(b"data2"): b"data2",
            compute_cid_v1(b"data3"): b"data3",
            compute_cid_v1(b"data4"): b"data4",
            compute_cid_v1(b"data5"): b"data5",
        }

        # Put all blocks
        for cid, data in blocks.items():
            await store.put_block(cid, data)

        # Verify all blocks exist
        for cid, data in blocks.items():
            assert await store.has_block(cid)
            retrieved = await store.get_block(cid)
            assert retrieved == data

        # Verify count
        all_cids = store.get_all_cids()
        assert len(all_cids) == len(blocks)

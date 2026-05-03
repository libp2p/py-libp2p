"""
Manual test for FilesystemBlockStore.

Tests:
  1. Basic put/get/has/delete round-trip
  2. Persistence: blocks survive store re-creation (simulates process restart)
  3. get_all_cids: scans the directory tree and returns all stored CIDs
  4. Drop-in replacement: swapping MemoryBlockStore → FilesystemBlockStore

Run with:
    python test_filesystem_blockstore.py
    or
    pytest test_filesystem_blockstore.py
"""

from pathlib import Path
import shutil
import tempfile

import pytest
import trio

from libp2p.bitswap.block_store import FilesystemBlockStore, MemoryBlockStore
from libp2p.bitswap.cid import CODEC_RAW, cid_to_text, compute_cid_v1

# ── helpers ──────────────────────────────────────────────────────────────────


def make_block(content: bytes) -> tuple[bytes, bytes]:
    """Return (cid_bytes, data) for a raw block."""
    cid = compute_cid_v1(content, codec=CODEC_RAW)
    return cid, content


def pass_fail(label: str, ok: bool) -> None:
    icon = "✅" if ok else "❌"
    print(f"  {icon}  {label}")
    if not ok:
        raise AssertionError(f"FAILED: {label}")


# ── pytest fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def store_path(tmp_path):
    """Provide a fresh temporary directory path for each test."""
    return str(tmp_path)


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.trio
async def test_basic_round_trip(store_path: str) -> None:
    print("\n[1] Basic put / get / has / delete")
    store = FilesystemBlockStore(store_path)

    cid, data = make_block(b"hello filesystem blockstore")

    # has_block → False before put
    pass_fail("has_block returns False before put", not await store.has_block(cid))

    # put_block
    await store.put_block(cid, data)
    pass_fail("block file exists on disk after put", store._cid_to_path(cid).exists())

    # get_block
    fetched = await store.get_block(cid)
    pass_fail("get_block returns correct data", fetched == data)

    # has_block → True after put
    pass_fail("has_block returns True after put", await store.has_block(cid))

    # delete_block
    await store.delete_block(cid)
    pass_fail("block file gone after delete", not store._cid_to_path(cid).exists())
    pass_fail("get_block returns None after delete", await store.get_block(cid) is None)


@pytest.mark.trio
async def test_persistence(store_path: str) -> None:
    print("\n[2] Persistence across store re-creation (simulates process restart)")

    # Write with first instance
    store1 = FilesystemBlockStore(store_path)
    cid1, data1 = make_block(b"block that should survive restart")
    cid2, data2 = make_block(b"another persistent block")
    await store1.put_block(cid1, data1)
    await store1.put_block(cid2, data2)
    pass_fail("2 blocks written by store1", store1.size() == 2)

    # Create a brand-new store object pointing to the same path
    # (simulates a process restart)
    store2 = FilesystemBlockStore(store_path)
    pass_fail(
        "store2 sees block1 written by store1", await store2.get_block(cid1) == data1
    )
    pass_fail(
        "store2 sees block2 written by store1", await store2.get_block(cid2) == data2
    )
    pass_fail("store2.size() == 2", store2.size() == 2)

    print(f"    Block directory: {store2.base_path()}")
    print(f"    CID1: {cid_to_text(cid1)}")
    print(f"    CID2: {cid_to_text(cid2)}")


@pytest.mark.trio
async def test_get_all_cids(store_path: str) -> None:
    print("\n[3] get_all_cids scans directory tree")
    store = FilesystemBlockStore(store_path)

    blocks = [make_block(f"block {i}".encode()) for i in range(5)]
    for cid, data in blocks:
        await store.put_block(cid, data)

    all_cids = store.get_all_cids()
    pass_fail(f"get_all_cids returns {len(blocks)} CIDs", len(all_cids) == len(blocks))

    stored_set = {bytes(c) for c in all_cids}
    for cid, _ in blocks:
        pass_fail(
            f"CID {cid_to_text(cid)[:20]}... is in get_all_cids",
            bytes(cid) in stored_set,
        )


@pytest.mark.trio
async def test_get_missing_returns_none(store_path: str) -> None:
    print("\n[4] get_block returns None for missing CID")
    store = FilesystemBlockStore(store_path)
    cid, _ = make_block(b"this block was never stored")
    result = await store.get_block(cid)
    pass_fail("get_block returns None for unknown CID", result is None)


@pytest.mark.trio
async def test_drop_in_for_memory_store(store_path: str) -> None:
    print("\n[5] Drop-in replacement for MemoryBlockStore")

    async def use_store(store) -> bytes:
        """Same code works for both store types."""
        cid, data = make_block(b"drop-in replacement test")
        await store.put_block(cid, data)
        return await store.get_block(cid)

    mem_result = await use_store(MemoryBlockStore())
    fs_result = await use_store(FilesystemBlockStore(store_path))

    pass_fail(
        "MemoryBlockStore and FilesystemBlockStore return same data",
        mem_result == fs_result,
    )


@pytest.mark.trio
async def test_directory_structure(store_path: str) -> None:
    print("\n[6] 2-char prefix directory structure")
    store = FilesystemBlockStore(store_path)
    cid, data = make_block(b"check directory layout")
    await store.put_block(cid, data)

    cid_str = cid_to_text(cid)
    expected_dir = Path(store_path) / cid_str[:2]
    expected_file = expected_dir / cid_str[2:]

    pass_fail(f"2-char prefix dir '{cid_str[:2]}' exists", expected_dir.is_dir())
    pass_fail(
        f"block file '{cid_str[2:8]}...' exists inside prefix dir",
        expected_file.exists(),
    )
    pass_fail("file contents match original data", expected_file.read_bytes() == data)

    print(f"    Path: {expected_file}")


# ── main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 60)
    print("FilesystemBlockStore — Manual Test Suite")
    print("=" * 60)

    # Each test gets its own temp directory so they don't interfere
    dirs = [tempfile.mkdtemp(prefix="fs_blockstore_test_") for _ in range(6)]

    try:
        await test_basic_round_trip(dirs[0])
        await test_persistence(dirs[1])
        await test_get_all_cids(dirs[2])
        await test_get_missing_returns_none(dirs[3])
        await test_drop_in_for_memory_store(dirs[4])
        await test_directory_structure(dirs[5])

        print("\n" + "=" * 60)
        print("✅  All tests passed!")
        print("=" * 60)

    finally:
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    trio.run(main)

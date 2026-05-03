"""
Test that add_file / add_bytes now produce dag-pb leaf blocks (UnixFS-wrapped)
and that balanced_layout builds the correct tree structure.

Run with:
    python test_unixfs_encoding.py
"""

import os
import tempfile

import trio

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import CODEC_DAG_PB, CODEC_RAW, cid_to_text, compute_cid_v1
from libp2p.bitswap.dag_pb import (
    MAX_LINKS_PER_NODE,
    balanced_layout,
    create_leaf_node,
    decode_dag_pb,
    is_file_node,
)


def ok(label):
    print(f"  OK  {label}")


def fail(label, detail=""):
    raise AssertionError(f"FAIL  {label}  {detail}")


# ── 1. create_leaf_node wraps data in dag-pb + UnixFS ────────────────────────
def test_create_leaf_node():
    print("\n[1] create_leaf_node")
    data = b"hello leaf"
    leaf = create_leaf_node(data)

    # Must be a valid dag-pb file node
    assert is_file_node(leaf), "leaf must be a dag-pb file node"
    ok("create_leaf_node produces a dag-pb file node")

    # Decode and check inline data
    links, unixfs = decode_dag_pb(leaf)
    assert links == [], "leaf must have no links"
    assert unixfs is not None
    assert unixfs.data == data, f"inline data mismatch: {unixfs.data!r} != {data!r}"
    assert unixfs.filesize == len(data)
    ok(f"leaf contains inline data ({len(data)} bytes), filesize={unixfs.filesize}")

    # CID must be dag-pb, not raw
    cid = compute_cid_v1(leaf, codec=CODEC_DAG_PB)
    raw_cid = compute_cid_v1(data, codec=CODEC_RAW)
    assert bytes(cid) != bytes(raw_cid), "dag-pb leaf CID must differ from raw CID"
    ok(f"leaf CID is dag-pb (not raw): {cid_to_text(cid)[:30]}...")

    # Empty leaf
    empty_leaf = create_leaf_node(b"")
    _, empty_unixfs = decode_dag_pb(empty_leaf)
    assert empty_unixfs is not None
    assert empty_unixfs.filesize == 0
    ok("empty leaf node is valid")


# ── 2. balanced_layout single leaf ───────────────────────────────────────────
def test_balanced_layout_single():
    print("\n[2] balanced_layout — single leaf returns leaf unchanged")
    data = b"only chunk"
    leaf = create_leaf_node(data)
    cid = compute_cid_v1(leaf, codec=CODEC_DAG_PB)

    root_cid, root_block = balanced_layout([(cid, leaf, len(data))])
    assert bytes(root_cid) == bytes(cid)
    assert root_block == leaf
    ok("single leaf: root_cid == leaf_cid")


# ── 3. balanced_layout two leaves ────────────────────────────────────────────
def test_balanced_layout_two_leaves():
    print("\n[3] balanced_layout — two leaves builds one root")
    leaves = []
    for i in range(2):
        data = f"chunk {i}".encode() * 100
        leaf = create_leaf_node(data)
        cid = compute_cid_v1(leaf, codec=CODEC_DAG_PB)
        leaves.append((cid, leaf, len(data)))

    root_cid, root_block = balanced_layout(leaves)

    # Root must be a dag-pb file node with 2 links
    assert is_file_node(root_block)
    links, unixfs = decode_dag_pb(root_block)
    assert len(links) == 2, f"expected 2 links, got {len(links)}"
    assert unixfs is not None
    assert unixfs.filesize == sum(s for _, _, s in leaves)
    assert len(unixfs.blocksizes) == 2
    ok(f"root has 2 links, filesize={unixfs.filesize}, blocksizes={unixfs.blocksizes}")


# ── 4. balanced_layout 175 leaves builds 2-level tree ────────────────────────
def test_balanced_layout_two_levels():
    print("\n[4] balanced_layout — 175 leaves builds 2-level tree (174 + 1)")
    n = MAX_LINKS_PER_NODE + 1  # 175
    chunk_size = 100
    leaves = []
    for i in range(n):
        data = bytes([i % 256]) * chunk_size
        leaf = create_leaf_node(data)
        cid = compute_cid_v1(leaf, codec=CODEC_DAG_PB)
        leaves.append((cid, leaf, chunk_size))

    root_cid, root_block = balanced_layout(leaves)
    links, unixfs = decode_dag_pb(root_block)

    # Root should link to 2 internal nodes (174 + 1)
    assert len(links) == 2, f"expected 2 top-level links, got {len(links)}"
    assert unixfs is not None
    assert unixfs.filesize == n * chunk_size
    ok("175 leaves → root has 2 links (174-leaf node + 1-leaf node)")
    ok(f"root filesize = {unixfs.filesize} = 175 * {chunk_size}")


# ── 5. balanced_layout 174 leaves stays flat ─────────────────────────────────
def test_balanced_layout_flat():
    print("\n[5] balanced_layout — exactly 174 leaves stays flat (1 level)")
    n = MAX_LINKS_PER_NODE  # 174
    leaves = []
    for i in range(n):
        data = bytes([i % 256]) * 50
        leaf = create_leaf_node(data)
        cid = compute_cid_v1(leaf, codec=CODEC_DAG_PB)
        leaves.append((cid, leaf, 50))

    root_cid, root_block = balanced_layout(leaves)
    links, unixfs = decode_dag_pb(root_block)

    assert len(links) == 174, f"expected 174 direct links, got {len(links)}"
    ok("174 leaves → flat root with 174 direct links")


# ── 6. add_file produces dag-pb leaves (not raw) via MerkleDag ───────────────
async def test_add_file_produces_dag_pb_leaves():
    print("\n[6] MerkleDag.add_file produces dag-pb leaf blocks")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    store = MemoryBlockStore()
    mock_client = MagicMock(spec=BitswapClient)
    mock_client.block_store = store
    stored: dict[bytes, bytes] = {}

    async def add_block_impl(cid, data):
        stored[bytes(cid)] = data

    mock_client.add_block = AsyncMock(side_effect=add_block_impl)

    dag = MerkleDag(mock_client)

    # Write a 3-chunk file
    chunk_size = 63 * 1024
    content = b"x" * (chunk_size * 3 - 7)  # 3 chunks
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(content)
        tmp = f.name

    try:
        root_cid = await dag.add_file(
            tmp, chunk_size=chunk_size, wrap_with_directory=False
        )
    finally:
        os.unlink(tmp)

    # Every stored block must be a dag-pb file node (no raw blocks)
    raw_blocks = []
    for cid_bytes, block_data in stored.items():
        if not is_file_node(block_data):
            raw_blocks.append(cid_to_text(cid_bytes)[:20])

    assert raw_blocks == [], f"Found non-dag-pb blocks: {raw_blocks}"
    ok(f"All {len(stored)} stored blocks are dag-pb file nodes (no raw blocks)")

    # Root must link to 3 leaves
    root_block = stored[bytes(root_cid)]
    links, unixfs = decode_dag_pb(root_block)
    assert len(links) == 3, f"expected 3 links on root, got {len(links)}"
    assert unixfs is not None
    assert unixfs.filesize == len(content)
    ok(f"root has 3 links, filesize={unixfs.filesize}")

    # Each leaf must contain inline UnixFS data
    for link in links:
        leaf_block = stored[bytes(link.cid)]
        leaf_links, leaf_unixfs = decode_dag_pb(leaf_block)
        assert leaf_links == [], "leaf must have no links"
        assert leaf_unixfs is not None and leaf_unixfs.data != b""
    ok("each leaf contains inline UnixFS data")


# ── 7. add_bytes produces dag-pb leaves ──────────────────────────────────────
async def test_add_bytes_produces_dag_pb_leaves():
    print("\n[7] MerkleDag.add_bytes produces dag-pb leaf blocks")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    store = MemoryBlockStore()
    mock_client = MagicMock(spec=BitswapClient)
    mock_client.block_store = store
    stored: dict[bytes, bytes] = {}

    async def add_block_impl(cid, data):
        stored[bytes(cid)] = data

    mock_client.add_block = AsyncMock(side_effect=add_block_impl)

    dag = MerkleDag(mock_client)
    content = b"y" * (63 * 1024 * 2 + 500)  # 3 chunks
    root_cid = await dag.add_bytes(content)

    raw_blocks = [cid_to_text(c)[:20] for c, d in stored.items() if not is_file_node(d)]
    assert raw_blocks == [], f"Found non-dag-pb blocks: {raw_blocks}"
    ok(f"All {len(stored)} stored blocks are dag-pb file nodes")

    root_block = stored[bytes(root_cid)]
    links, unixfs = decode_dag_pb(root_block)
    assert len(links) == 3
    assert unixfs is not None
    assert unixfs.filesize == len(content)
    ok(f"root has 3 links, filesize={unixfs.filesize}")


# ── main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("UnixFSFile / Balanced DAG — Test Suite")
    print("=" * 60)

    test_create_leaf_node()
    test_balanced_layout_single()
    test_balanced_layout_two_leaves()
    test_balanced_layout_two_levels()
    test_balanced_layout_flat()
    await test_add_file_produces_dag_pb_leaves()
    await test_add_bytes_produces_dag_pb_leaves()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    trio.run(main)

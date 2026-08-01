"""
Test io.IOBase input support — chunk_stream() and MerkleDag.add_stream().

Run with:
    python test_io_stream.py
"""

import gzip
import io
import os
import tempfile

import trio

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.chunker import DEFAULT_CHUNK_SIZE, chunk_stream
from libp2p.bitswap.cid import cid_to_text


def ok(label):
    print(f"  OK  {label}")


# ── 1. chunk_stream basics ────────────────────────────────────────────────────


def test_chunk_stream_bytesio():
    print("\n[1] chunk_stream — BytesIO")
    data = b"x" * (DEFAULT_CHUNK_SIZE * 3 + 100)  # 3 full + 1 partial chunk
    chunks = list(chunk_stream(io.BytesIO(data), DEFAULT_CHUNK_SIZE))
    assert len(chunks) == 4
    assert b"".join(chunks) == data
    assert len(chunks[0]) == DEFAULT_CHUNK_SIZE
    assert len(chunks[-1]) == 100
    ok(f"4 chunks, sizes: {[len(c) for c in chunks]}")


def test_chunk_stream_empty():
    print("\n[2] chunk_stream — empty stream yields nothing")
    chunks = list(chunk_stream(io.BytesIO(b"")))
    assert chunks == []
    ok("empty stream yields no chunks")


def test_chunk_stream_file_handle():
    print("\n[3] chunk_stream — real file handle")
    data = b"file handle test " * 5000
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        with open(tmp, "rb") as fh:
            chunks = list(chunk_stream(fh))
        assert b"".join(chunks) == data
        ok(f"file handle: {len(chunks)} chunks, {len(data)} bytes total")
    finally:
        os.unlink(tmp)


def test_chunk_stream_gzip():
    print("\n[4] chunk_stream — gzip stream (decompress on-the-fly)")
    original = b"compressed data " * 10000
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(original)
    buf.seek(0)

    with gzip.GzipFile(fileobj=buf, mode="rb") as gz:
        chunks = list(chunk_stream(gz))

    assert b"".join(chunks) == original
    ok(f"gzip stream: {len(chunks)} chunks, {len(original)} bytes decompressed")


def test_chunk_stream_matches_chunk_bytes():
    print("\n[5] chunk_stream produces same chunks as chunk_bytes")
    from libp2p.bitswap.chunker import chunk_bytes

    data = os.urandom(DEFAULT_CHUNK_SIZE * 5 + 777)
    stream_chunks = list(chunk_stream(io.BytesIO(data)))
    bytes_chunks = chunk_bytes(data)
    assert stream_chunks == bytes_chunks
    ok(f"chunk_stream == chunk_bytes for {len(data)} bytes of random data")


# ── 2. MerkleDag.add_stream ───────────────────────────────────────────────────


async def test_add_stream_bytesio():
    print("\n[6] add_stream — BytesIO produces same CID as add_bytes")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    store = MemoryBlockStore()
    mock = MagicMock(spec=BitswapClient)
    mock.block_store = store
    stored: dict[bytes, bytes] = {}

    async def add_block(cid, data):
        stored[bytes(cid)] = data

    mock.add_block = AsyncMock(side_effect=add_block)

    dag = MerkleDag(mock)
    data = b"same content " * 5000

    cid_bytes = await dag.add_bytes(data)
    stored.clear()
    cid_stream = await dag.add_stream(io.BytesIO(data))

    assert bytes(cid_bytes) == bytes(cid_stream), (
        f"CIDs differ:\n  add_bytes:  {cid_to_text(cid_bytes)}\n"
        f"  add_stream: {cid_to_text(cid_stream)}"
    )
    ok(f"add_stream CID == add_bytes CID: {cid_to_text(cid_stream)[:30]}...")


async def test_add_stream_empty():
    print("\n[7] add_stream — empty stream stores single empty leaf")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    store = MemoryBlockStore()
    mock = MagicMock(spec=BitswapClient)
    mock.block_store = store
    stored: dict[bytes, bytes] = {}

    async def add_block(cid, data):
        stored[bytes(cid)] = data

    mock.add_block = AsyncMock(side_effect=add_block)

    dag = MerkleDag(mock)
    await dag.add_stream(io.BytesIO(b""))

    assert len(stored) == 1
    block = list(stored.values())[0]
    assert block == b""
    ok("empty stream → 1 empty raw leaf block stored")


async def test_add_stream_single_chunk():
    print("\n[8] add_stream — single chunk returns leaf CID directly (no root node)")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    store = MemoryBlockStore()
    mock = MagicMock(spec=BitswapClient)
    mock.block_store = store
    stored: dict[bytes, bytes] = {}

    async def add_block(cid, data):
        stored[bytes(cid)] = data

    mock.add_block = AsyncMock(side_effect=add_block)

    dag = MerkleDag(mock)
    data = b"small enough to be one chunk"
    root_cid = await dag.add_stream(io.BytesIO(data))

    assert len(stored) == 1, f"expected 1 block, got {len(stored)}"
    block = stored[bytes(root_cid)]
    assert block == data
    ok("single chunk: leaf CID returned directly, inline data correct")


async def test_add_stream_gzip():
    print("\n[9] add_stream — gzip stream decompresses and adds correctly")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    original = b"gzip content " * 20000  # ~260 KB — 2 chunks after decompress

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(original)
    compressed_size = buf.tell()
    buf.seek(0)

    store = MemoryBlockStore()
    mock = MagicMock(spec=BitswapClient)
    mock.block_store = store
    stored: dict[bytes, bytes] = {}

    async def add_block(cid, data):
        stored[bytes(cid)] = data

    mock.add_block = AsyncMock(side_effect=add_block)

    dag = MerkleDag(mock)

    with gzip.GzipFile(fileobj=buf, mode="rb") as gz:
        root_cid = await dag.add_stream(gz)

    # Since it's < 256KB, it's a single raw chunk
    root_block = stored[bytes(root_cid)]
    assert root_block == original
    ok(
        f"gzip stream: {compressed_size} compressed → {len(original)} bytes added "
        f"as a single chunk"
    )


async def test_add_stream_vs_add_file_same_cid():
    print("\n[10] add_stream(open(f)) produces same CID as add_file(path)")
    from unittest.mock import AsyncMock, MagicMock

    from libp2p.bitswap.client import BitswapClient
    from libp2p.bitswap.dag import MerkleDag

    data = b"compare stream vs file " * 8000  # ~176 KB, 3 chunks

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        tmp = f.name

    try:

        def make_dag():
            store = MemoryBlockStore()
            mock = MagicMock(spec=BitswapClient)
            mock.block_store = store
            stored = {}

            async def add_block(cid, d):
                stored[bytes(cid)] = d

            mock.add_block = AsyncMock(side_effect=add_block)
            return MerkleDag(mock)

        dag1 = make_dag()
        cid_file = await dag1.add_file(tmp, wrap_with_directory=False)

        dag2 = make_dag()
        with open(tmp, "rb") as fh:
            cid_stream = await dag2.add_stream(fh)

        assert bytes(cid_file) == bytes(cid_stream), (
            f"CIDs differ:\n  add_file:   {cid_to_text(cid_file)}\n"
            f"  add_stream: {cid_to_text(cid_stream)}"
        )
        ok(f"add_file == add_stream CID: {cid_to_text(cid_file)[:30]}...")
    finally:
        os.unlink(tmp)


# ── main ──────────────────────────────────────────────────────────────────────


async def main():
    print("=" * 60)
    print("io.IOBase Input Support — Test Suite")
    print("=" * 60)

    # sync tests
    test_chunk_stream_bytesio()
    test_chunk_stream_empty()
    test_chunk_stream_file_handle()
    test_chunk_stream_gzip()
    test_chunk_stream_matches_chunk_bytes()

    # async tests
    await test_add_stream_bytesio()
    await test_add_stream_empty()
    await test_add_stream_single_chunk()
    await test_add_stream_gzip()
    await test_add_stream_vs_add_file_same_cid()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    trio.run(main)

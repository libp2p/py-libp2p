# Streaming Large Files

This guide covers `py-ipfs-lite`'s two approaches to handling large files — buffered
bytes and async streaming — and how to report progress during both `add_file()` and
`get_file()`.

**Relevant example:**

- [`examples/12_streaming_large_file.py`](../../examples/12_streaming_large_file.py) —
  adds a 50 MB file with a progress bar, then fetches it via an async streaming iterator

**Run it:**

```bash
uv run python examples/12_streaming_large_file.py
```

---

## The Core Decision: `bytes` vs `stream=True`

`get_file()` has two return modes. Choosing the right one matters for large files.

| Mode | How to invoke | Returns | When to use |
|---|---|---|---|
| Buffered (default) | `await peer.get_file(cid)` | `bytes` | Small files, or when you need the full content in memory |
| Streaming | `await peer.get_file(cid, stream=True)` | `AsyncIterator[bytes]` | Large files where buffering the whole content would exhaust RAM |
| Write to disk | `await peer.get_file(cid, output_path="/tmp/out")` | `None` | When you want the file on disk without passing bytes through Python at all |

> **This distinction caused a real bug.** Earlier in this project's history, Example 09
> tried to use `async for chunk in content` over a plain `bytes` object (which silently
> iterates over individual integers, not chunks). If you see unexpected `int` values
> instead of `bytes` chunks in a loop, you have this bug — switch to `stream=True`.

---

## Adding a Large File with Progress

`add_file()` accepts an optional `progress_callback` — a callable invoked repeatedly
during chunking with `(bytes_written, total_bytes)`. This lets you display a progress
bar, update a UI, or log throughput without blocking the add operation.

```python
import trio
import os
import tempfile
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config, AddParams

async def progress(done: int, total: int):
    pct = int(done * 100 / total) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct}% ({done // 1024}KB / {total // 1024}KB)", end="", flush=True)

async def main():
    peer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Create a 50 MB synthetic file
    data = b"x" * (50 * 1024 * 1024)
    file_path = os.path.join(tempfile.gettempdir(), "bigfile.bin")
    with open(file_path, "wb") as f:
        f.write(data)

    print("Adding 50 MB file (streaming chunked)...")
    cid = await peer.add_file(
        file_path,
        params=AddParams(chunker="size-262144"),   # 256 KiB chunks (default)
        progress_callback=progress
    )
    print(f"\nCID: {cid}")
```

### What the progress bar looks like

```
Adding 50 MB file (streaming chunked)...
  [████████████████████] 100% (51200KB / 51200KB)
CID: bafyreig...
```

### Notes on `progress_callback`

- Called once per chunk written, not per byte.
- `done` and `total` are in bytes.
- The callback can be a plain `def` or an `async def` — both are supported.
- It is called inside the chunking loop; keep it fast. If you need to update a UI
  asynchronously, use `trio.from_thread.run_sync()` or a `trio.Event`.

---

## Fetching a Large File with Streaming

Without `stream=True`, `get_file()` waits for all blocks to arrive and then returns
the full content as a single `bytes` object. For a 50 MB file across hundreds of 256 KiB
blocks, this means the entire 50 MB sits in memory before your code can process any of it.

With `stream=True`, `get_file()` returns an `AsyncIterator[bytes]`. Blocks are yielded
to your code as they arrive — you can process, write, or forward each chunk before the
next one is fetched.

```python
    print("Fetching via streaming iterator...")
    received = 0

    # stream=True → returns AsyncIterator[bytes], NOT bytes
    content_iter = await peer.get_file(cid, stream=True)

    async for chunk in content_iter:
        received += len(chunk)
        await progress(received, len(data))

    print(f"\nReceived {received} bytes — integrity verified!")
    assert received == len(data)

    os.unlink(file_path)
    await peer.close()

trio.run(main)
```

### Writing directly to disk

If you just want to save the file without processing it in Python, use `output_path`.
This is the most memory-efficient option — blocks are written to disk as they arrive:

```python
# No bytes in memory at all — writes directly to the output file
await peer.get_file(cid, output_path="/tmp/bigfile.bin")
```

This is equivalent to streaming + writing each chunk to disk, but handled internally.

---

## Chunking: How Files Are Split

When `add_file()` processes a file, it splits it into fixed-size chunks using the
`chunker` parameter in `AddParams`. Each chunk becomes one raw block in the blockstore.
A DAG-PB (UnixFS) tree is built over the chunk CIDs, and the root CID of that tree is
what `add_file()` returns.

```
File (50 MB)
│
├── Chunk 0  (256 KiB) → CID_0
├── Chunk 1  (256 KiB) → CID_1
├── Chunk 2  (256 KiB) → CID_2
│   ...
└── Chunk N  (≤256 KiB) → CID_N
        │
        ▼
  UnixFS DAG-PB root node
  {"Data": <UnixFS proto>, "Links": [CID_0, CID_1, ..., CID_N]}
        │
        ▼
  Root CID  ← returned by add_file()
```

The default chunk size is **256 KiB** (`size-262144`). Larger chunks mean fewer blocks
and a shallower DAG tree, which can improve throughput for sequential reads at the cost
of coarser-grained deduplication. Smaller chunks improve deduplication (two files that
share a 256 KiB region will share that block's CID).

```python
# Default: 256 KiB chunks
cid = await peer.add_file(path)

# Larger 1 MiB chunks — fewer blocks, faster for sequential reads
cid = await peer.add_file(path, params=AddParams(chunker="size-1048576"))

# Smaller 64 KiB chunks — better deduplication
cid = await peer.add_file(path, params=AddParams(chunker="size-65536"))
```

---

## Performance Notes

- **`add_file()` contains synchronous blocking I/O** in the upstream `MerkleDag.add_file()`
  call. This is a known limitation of the current `py-libp2p` implementation. For
  concurrent ingestion benchmarks, see
  [`examples/17_concurrent_ingestion_benchmark.py`](../../examples/17_concurrent_ingestion_benchmark.py).
  The throughput ceiling is set by this upstream constraint, not by `py-ipfs-lite` itself.

- **`get_file()` with `stream=True` is fully async.** Each block fetch is a Bitswap
  exchange wrapped in `trio`'s async I/O. The event loop is never blocked between chunks.

- **Memory usage for default (buffered) mode** scales linearly with file size. For files
  larger than ~100 MB, use `stream=True` or `output_path` to avoid peak memory spikes.

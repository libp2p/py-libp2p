# Persistence and Garbage Collection

This guide explains how `py-ipfs-lite` stores blocks locally, how pinning protects
data from being deleted, and how garbage collection reclaims space.

**Relevant examples:**

- [`examples/04_pin_and_gc.py`](../../examples/04_pin_and_gc.py) — pinning and GC
- [`examples/05a_localstore_write.py`](../../examples/05a_localstore_write.py) — writing to a filesystem blockstore
- [`examples/05b_localstore_read.py`](../../examples/05b_localstore_read.py) — reading back after a process restart

**Run them:**

```bash
uv run python examples/04_pin_and_gc.py
uv run python examples/05a_localstore_write.py
# note the CID printed, then:
uv run python examples/05b_localstore_read.py <cid>
```

______________________________________________________________________

## Blockstore Types

Every block stored in `py-ipfs-lite` lives in the **blockstore** — a key/value store
keyed by CID. Two implementations are available:

| Type       | Config value             | Persistence               | Best for                           |
| ---------- | ------------------------ | ------------------------- | ---------------------------------- |
| Filesystem | `"filesystem"` (default) | Survives process restarts | Production, daemons, CAR workflows |
| In-memory  | `"memory"`               | Lost on process exit      | Tests, short-lived agents, CI      |

```python
# Default: filesystem blockstore at .py_ipfs_lite/blocks
peer = Peer(Config(), listen_addrs=["/ip4/0.0.0.0/tcp/4001"])

# Explicit filesystem with a custom path
peer = Peer(
    Config(blockstore_type="filesystem", blockstore_path="/data/ipfs/blocks"),
    listen_addrs=["/ip4/0.0.0.0/tcp/4001"]
)

# In-memory (test-friendly)
peer = Peer(
    Config(blockstore_type="memory"),
    listen_addrs=["/ip4/127.0.0.1/tcp/0"]
)
```

______________________________________________________________________

## Example 05a + 05b: Surviving a Process Restart

[`examples/05a_localstore_write.py`](../../examples/05a_localstore_write.py) +
[`examples/05b_localstore_read.py`](../../examples/05b_localstore_read.py)

These two scripts prove that the filesystem blockstore persists across independent
Python processes.

### Writing (05a)

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    config = Config(
        blockstore_type="filesystem",
        blockstore_path="./demo_blocks",
        reprovide_interval_seconds=-1,
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    cid = await peer.add_node({"note": "this should survive a process restart"})
    print(f"Stored CID: {cid}")

    await peer.close()

trio.run(main)
```

When the process exits, the block file stays in `./demo_blocks/`. The CID is a
deterministic hash of the data, so it will be identical in any future process that stores
the same dict.

### Reading back after restart (05b)

```python
import sys
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main(cid: str):
    # Exact same config — opens the same blockstore directory
    config = Config(
        blockstore_type="filesystem",
        blockstore_path="./demo_blocks",
        reprovide_interval_seconds=-1,
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # No network needed — the block is already on disk
    data = await peer.get_node(cid)
    print(data)   # {"note": "this should survive a process restart"}

    await peer.close()

trio.run(main, sys.argv[1])
```

The key insight: `get_node()` checks the local blockstore first. If the block is found
there, no network request is made at all. The filesystem blockstore is what makes this
work across restarts.

______________________________________________________________________

## Example 04: Pinning and Garbage Collection

[`examples/04_pin_and_gc.py`](../../examples/04_pin_and_gc.py)

### The problem: blocks accumulate

Every `add_file()` and `add_node()` call writes blocks to the blockstore. Blocks fetched
from the network via Bitswap are also cached locally. Without a mechanism to remove
stale blocks, the blockstore grows unboundedly.

Garbage collection (GC) solves this — but it needs to know which blocks are "in use"
and must not be deleted. That is what pinning provides.

### Pin types

| Type        | Created by                      | What it protects                                                                |
| ----------- | ------------------------------- | ------------------------------------------------------------------------------- |
| `recursive` | `add_pin(cid, recursive=True)`  | Root block + all blocks reachable from it                                       |
| `direct`    | `add_pin(cid, recursive=False)` | Root block only                                                                 |
| `indirect`  | Automatically                   | Blocks reachable from a `recursive` pin (cannot be directly created or deleted) |

For most use cases, recursive pinning is what you want. Direct pinning is useful when
you have a large DAG and only want to protect the root node itself, not its children.

### Full walkthrough

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config
from libp2p.bitswap.cid import parse_cid

async def main():
    peer = Peer(
        Config(reprovide_interval_seconds=-1),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Store two blocks
    cid_keep = await peer.add_node({"name": "pinned-log"})
    cid_drop = await peer.add_node({"name": "unpinned-log"})
    print(f"Will keep: {cid_keep}")
    print(f"Will drop: {cid_drop}")

    # Pin only the first one (direct pin — single block)
    await peer.add_pin(cid_keep, recursive=False)
    print(f"Pinned: {cid_keep}")

    # Run GC — deletes all blocks not reachable from a pin
    stats = await peer.gc()
    print(f"Reclaimed: {stats.reclaimed_blocks} blocks")
    print(f"Retained:  {stats.retained_blocks} blocks")

    # Verify
    keep_present = await peer.blockstore.has(parse_cid(cid_keep))
    drop_present = await peer.blockstore.has(parse_cid(cid_drop))

    assert keep_present is True    # pinned → survived GC
    assert drop_present is False   # unpinned → deleted by GC
    print("✓ GC removed only the unpinned block")

    await peer.close()

trio.run(main)
```

### What GC returns

```python
stats = await peer.gc()
# stats is a GCResult dataclass:
# {
#   "reclaimed_blocks": 1,   # blocks deleted
#   "retained_blocks":  1    # blocks kept (reachable from pins)
# }
```

______________________________________________________________________

## How GC interacts with concurrent operations

GC uses an exclusive write lock (`RWLock`). This has two practical consequences:

1. **`add_file()` and `add_node()` are safe to call concurrently with each other** —
   they both hold the lock in *read* mode, so they run in parallel.

1. **GC waits for all in-flight writes to complete** before it acquires the exclusive
   lock. A block that is being written during a GC run will either be fully committed
   before GC starts (and may be reclaimed if unpinned), or GC will wait for it.

You do not need to manually serialize GC against your write operations. The lock handles
this automatically.

```
time ─────────────────────────────────────────────────────►
       add_node()  add_node()  gc()      add_node()
       [─────────][─────────][XXXXXXXX][──────────]
                              ↑
                    GC waits for all readers to finish,
                    then takes exclusive write lock
```

______________________________________________________________________

## API Quick Reference

| Method                                    | Description                                  |
| ----------------------------------------- | -------------------------------------------- |
| `await peer.add_pin(cid, recursive=True)` | Pin a CID (and optionally all linked blocks) |
| `await peer.remove_pin(cid)`              | Unpin a CID — block becomes GC-eligible      |
| `await peer.list_pins(type_filter="all")` | List all pinned CIDs                         |
| `await peer.gc()`                         | Run mark-and-sweep GC; returns `GCResult`    |
| `await peer.has_block(cid)`               | Check if a block exists locally              |
| `await peer.remove_node(cid)`             | Delete a single block (bypasses pin check)   |

For full parameter details, see the [Python SDK reference](../reference/python-sdk.md).

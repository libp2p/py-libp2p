# Tutorial 01: Your First Peer

By the end of this tutorial you will have:

- Installed `py-ipfs-lite` and its dependencies
- Started an in-memory IPFS peer inside a Python script
- Added a file and received its CID
- Stored a structured IPLD node and fetched it back
- Understood what a CID actually is

**Time:** ~10 minutes
**Prerequisites:** Python 3.12+, [`uv`](https://docs.astral.sh/uv/) installed

______________________________________________________________________

## Step 1 — Install

Clone the repository and install dependencies with `uv`:

```bash
git clone https://github.com/sumanjeet0012/py-ipfs-lite.git
cd py-ipfs-lite
uv sync
```

Verify everything is wired up:

```bash
uv run py-ipfs-lite --help
```

You should see the list of subcommands (`daemon`, `add`, `get`, `dag-export`,
`dag-import`).

______________________________________________________________________

## Step 2 — Start an In-Memory Peer

Create a new file called `my_first_peer.py` with the following content:

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    # Config with an in-memory blockstore — nothing is written to disk
    # reprovide_interval_seconds=-1 means the Reprovider background task is disabled
    # (no DHT announcements — fine for a local tutorial)
    peer = Peer(
        Config(blockstore_type="memory", reprovide_interval_seconds=-1),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]  # pick a random free port
    )

    await peer.start()

    print(f"Peer ID:  {peer.host.id()}")
    print(f"Address:  {peer.host.addrs()[0]}")

    # ... we will add code here in the next steps ...

    await peer.close()
    print("Peer closed cleanly.")

trio.run(main)
```

Run it:

```bash
uv run python my_first_peer.py
```

Expected output:

```
Peer ID:  12D3KooW...
Address:  /ip4/127.0.0.1/tcp/54321/p2p/12D3KooW...
Peer closed cleanly.
```

Every time you run this script a **new random PeerID** is generated because we are not
passing a fixed key pair. The port number also changes because `tcp/0` asks the OS to
pick a free port. This is intentional for ephemeral peers — for a stable daemon, see
Tutorial 02.

______________________________________________________________________

## Step 3 — Add a File

Create a small test file and add it to the peer's blockstore:

```python
import trio
import tempfile
import os
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(
        Config(blockstore_type="memory", reprovide_interval_seconds=-1),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Write a small test file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
        f.write("Hello from py-ipfs-lite!\n")
        tmp_path = f.name

    # Add it — py-ipfs-lite chunks it, builds a UnixFS DAG, returns the root CID
    cid = await peer.add_file(tmp_path)
    print(f"File CID: {cid}")

    # Fetch it back — get_file returns bytes by default
    content = await peer.get_file(cid)
    print(f"Content:  {content.decode()}")

    os.unlink(tmp_path)
    await peer.close()

trio.run(main)
```

Run it:

```bash
uv run python my_first_peer.py
```

Expected output:

```
File CID: bafkrei...
Content:  Hello from py-ipfs-lite!
```

> **What just happened?**
>
> `add_file()` split the file into 256 KiB chunks (there's only one here — the file is
> tiny), computed the SHA-256 hash of the chunk, encoded it as a UnixFS DAG-PB node,
> wrote it to the in-memory blockstore, and returned the root CID.
>
> `get_file()` looked up the CID in the local blockstore, found it immediately (no
> network request needed), decoded the UnixFS structure, and returned the raw bytes.

______________________________________________________________________

## What Is a CID?

A **CID (Content Identifier)** is a self-describing, content-addressed label. It encodes:

1. **A hash of the data** — SHA-256 of the block bytes
1. **The hash function used** — so verifiers know how to re-compute it
1. **The codec** — how the bytes are structured (DAG-PB for files, DAG-CBOR/JSON for nodes)
1. **The CID version** — CIDv1 (base32 string, starts with `bafy...` or `bafk...`)

This means **the CID is the verification**. When `get_file()` returns bytes, it has
already verified that those bytes hash to the expected CID. It is not possible to
receive tampered content without the CID check failing.

The same data always produces the same CID, on any machine, in any language. A file
added by Python will have the same CID as the same file added by Kubo.

______________________________________________________________________

## Step 4 — Add a Structured IPLD Node

Beyond raw files, `py-ipfs-lite` can store arbitrary structured data as IPLD nodes.
This is what the AI agent memory examples use under the hood.

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(
        Config(blockstore_type="memory", reprovide_interval_seconds=-1),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Store a Python dict as a DAG-CBOR node
    log_entry = {
        "agent": "summarizer-agent-01",
        "model": "claude-sonnet-4-6",
        "prompt_hash": "bafy...exampleprompthash",
        "timestamp": "2026-06-18T12:00:00Z",
    }

    # dag-cbor: deterministic, compact encoding
    cid = await peer.add_node(log_entry, codec="dag-cbor")
    print(f"Node CID: {cid}")

    # Fetch it back — get_node decodes it back to a Python dict
    fetched = await peer.get_node(cid)
    print(f"Fetched:  {fetched}")

    # The CID guarantees this will always be True
    assert fetched == log_entry
    print("Data integrity verified via CID!")

    await peer.close()

trio.run(main)
```

Run it:

```bash
uv run python my_first_peer.py
```

Expected output:

```
Node CID: bafyrei...
Fetched:  {'agent': 'summarizer-agent-01', 'model': 'claude-sonnet-4-6', ...}
Data integrity verified via CID!
```

> **DAG-CBOR vs DAG-JSON**
>
> Both codecs store the same data — the difference is encoding.
>
> - `dag-cbor` is binary, compact, and **deterministic** (same dict → same bytes → same CID, always). Use it for production and linked DAGs.
> - `dag-json` is human-readable JSON. Easier to inspect, but slightly larger on disk.
>
> For linked DAGs (nodes that reference other nodes), use `dag-cbor` and include IPLD
> link objects: `{"prev": {"/": other_cid}}`.

______________________________________________________________________

## Step 5 — Fetch It Back and Close

Here is the complete, working script combining everything from this tutorial:

```python
import trio
import tempfile
import os
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    print("=== Tutorial 01: Your First Peer ===\n")

    peer = Peer(
        Config(blockstore_type="memory", reprovide_interval_seconds=-1),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()
    print(f"Started peer {peer.host.id()}\n")

    # 1. Add a file
    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt") as f:
        f.write("Hello from py-ipfs-lite!\n")
        tmp_path = f.name

    file_cid = await peer.add_file(tmp_path)
    print(f"[add_file]  CID: {file_cid}")
    content = await peer.get_file(file_cid)
    print(f"[get_file]  Content: {content.decode().strip()}")
    os.unlink(tmp_path)

    # 2. Add a structured node
    node_cid = await peer.add_node(
        {"agent": "summarizer-01", "timestamp": "2026-06-18T12:00:00Z"},
        codec="dag-cbor"
    )
    print(f"\n[add_node]  CID: {node_cid}")
    node = await peer.get_node(node_cid)
    print(f"[get_node]  Data: {node}")

    print("\nAll done — closing peer cleanly.")
    await peer.close()

trio.run(main)
```

______________________________________________________________________

## What You Just Did — Recap

| Action                             | API         | What happened internally                                     |
| ---------------------------------- | ----------- | ------------------------------------------------------------ |
| `Peer(Config(...), ...)`           | Constructor | Allocated subsystem objects (not started yet)                |
| `await peer.start()`               | Lifecycle   | Started libp2p host, blockstore, Bitswap, background tasks   |
| `await peer.add_file(path)`        | File op     | Chunked file → DAG-PB → blockstore write → returned root CID |
| `await peer.get_file(cid)`         | File op     | Local blockstore hit → UnixFS decode → returned bytes        |
| `await peer.add_node(dict, codec)` | DAG op      | CBOR encode → CID compute → blockstore write                 |
| `await peer.get_node(cid)`         | DAG op      | Local blockstore hit → CBOR decode → returned dict           |
| `await peer.close()`               | Lifecycle   | Cancelled background tasks, closed host connections          |

______________________________________________________________________

## What's Next?

| I want to…                                  | Go to…                                                    |
| ------------------------------------------- | --------------------------------------------------------- |
| Run a long-lived daemon with the HTTP API   | [Tutorial 02: Running a Daemon](./02-running-a-daemon.md) |
| Transfer content between two peers          | [DHT and Routing guide](../guides/dht-and-routing.md)     |
| Store a linked agent memory chain           | [AI Agents and RAG guide](../guides/ai-agents-and-rag.md) |
| Understand what's happening inside the peer | [Architecture](../architecture.md)                        |
| See the full list of examples               | [Examples Index](../reference/examples-index.md)          |

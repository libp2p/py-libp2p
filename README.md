# py-ipfs-lite

**py-ipfs-lite** is a lightweight, embeddable Python IPFS peer built on top of `py-libp2p`. 
It provides the core features of IPFS (Blockstore, Bitswap, DHT, IPNI, IPNS, and IPLD DAGs) without the overhead of a heavy Kubo daemon. 

It is designed to be highly interoperable with standard IPFS implementations like Kubo and go-ipfs-lite, natively supporting `dag-cbor`, CARv1 file import/export, Bitswap streaming, and more.

## Features

- **Embedded IPFS Node:** Run a complete IPFS node purely in Python using `trio` or standard async.
- **Bitswap Protocol:** Interoperate and exchange blocks directly with Kubo daemons.
- **KadDHT & IPNI Routing:** Local block lookups with lightning-fast routing via the KadDHT network and Delegated HTTP IPNI (`cid.contact`).
- **IPLD DAG Support:** Fully supports `dag-pb`, `dag-cbor`, and `dag-json` for building decentralized knowledge graphs, versioned datasets, and agent memory chains.
- **Offline Data Bundles (CAR):** Export and import full or partial DAGs as Content Addressable aRchives (`.car`).
- **IPNS Mutable Pointers:** Publish and resolve cryptographically signed mutable pointers (IPNS).
- **FastAPI HTTP Daemon:** A drop-in, Kubo-compatible HTTP API exposing `/api/v0` endpoints for adding files, fetching DAGs, and pinning.
- **Prometheus Metrics:** Integrated observability for garbage collection, block sizes, and Bitswap traffic.

## Installation

py-ipfs-lite uses `uv` for dependency management.

```bash
# Clone the repository
git clone https://github.com/sumanjeet0012/py-ipfs-lite.git
cd py-ipfs-lite

# Install dependencies using uv
uv sync
```

## Quickstart

### 1. The Python SDK (Embedded Peer)

You can run an IPFS peer directly inside your Python application using `trio`:

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    # Start an ephemeral in-memory peer
    peer = Peer(Config(blockstore_type="memory"), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # Add a file
    cid = await peer.add_file("/path/to/my/file.txt")
    print(f"Added file with CID: {cid}")

    # Build an IPLD DAG
    node_cid = await peer.add_node({"title": "Hello World", "author": "py-ipfs-lite"}, codec="dag-cbor")
    print(f"Added DAG node with CID: {node_cid}")

    # Publish to IPNS
    ipns_name = await peer.publish_name(f"/ipfs/{node_cid}")
    print(f"Published to IPNS: {ipns_name}")

    await peer.close()

if __name__ == "__main__":
    trio.run(main)
```

### 2. The CLI Daemon & HTTP API

You can spin up `py-ipfs-lite` as a standalone daemon that provides a Kubo-compatible HTTP API.

```bash
# Run the daemon on port 4001, exposing the HTTP API on port 5001
uv run py-ipfs-lite daemon --api --api-port 5001
```

Then you can use the standard HTTP API to interact with it:

```bash
# Add a file
curl -X POST -F file=@test.txt http://127.0.0.1:5001/api/v0/add

# Fetch an IPLD node
curl -X POST "http://127.0.0.1:5001/api/v0/dag/get?arg=bafy..."
```

## What's Next

| I want to… | Go to… |
|---|---|
| Understand how `py-ipfs-lite` is structured internally | [docs/architecture.md](docs/architecture.md) |
| Build verifiable AI agent memory / RAG pipelines | [docs/guides/ai-agents-and-rag.md](docs/guides/ai-agents-and-rag.md) |
| Export a DAG as a CAR file for Filecoin storage | [docs/guides/car-files-and-filecoin.md](docs/guides/car-files-and-filecoin.md) |
| Use IPNS mutable pointers and understand the trust model | [docs/guides/ipns.md](docs/guides/ipns.md) |
| Interoperate with a live Kubo daemon over Bitswap | [docs/guides/interop-with-kubo.md](docs/guides/interop-with-kubo.md) |
| See the full list of all 21 examples with one-line descriptions | [docs/reference/examples-index.md](docs/reference/examples-index.md) |
| Browse all documentation | [docs/index.md](docs/index.md) |

## License
MIT License

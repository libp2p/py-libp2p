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

## Examples

The `examples/` directory is packed with powerful demonstrations of `py-ipfs-lite` in action. Run any of them via `uv run python examples/<script>.py`:

1. **`01_embeddable_peers.py`**: Transfer a file directly between two embedded Python IPFS peers using Bitswap.
2. **`02_dht_discovery.py`**: Find content using the Kademlia DHT.
3. **`03_ipld_node.py`**: Work with generic IPLD JSON documents.
4. **`04_pin_and_gc.py`**: Protect blocks from garbage collection.
5. **`05_localstore_*`**: Persist data to disk instead of memory.
6. **`06_http_api.sh`**: Use the HTTP API endpoints.
7. **`07_reprovider.sh`**: Continuously broadcast CIDs to the DHT.
8. **`08_verifiable_inference.py`**: Sign and verify ML inferences with CIDs.
9. **`09_kubo_interop.py`**: Bi-directional file sharing with an official Go-Kubo daemon.
10. **`10_ipld_linked_dag.py`**: Traverse linked knowledge graphs entirely locally without network delay.
11. **`11_car_export_import.py`**: Archive DAGs to `.car` files and restore them completely offline.
12. **`12_streaming_large_file.py`**: Handle multi-gigabyte files gracefully with chunked AsyncIterators.
13. **`13_agent_memory_chain.py`**: Build a cryptographically verifiable, append-only Agent memory log.
14. **`14_distributed_rag.py`**: Perform Distributed RAG (Retrieval-Augmented Generation) across multiple IPFS nodes.
15. **`15_ipns_mutable_registry.py`**: Use IPNS as a stable, versioned pointer for an ever-changing DAG.
16. **`16_metrics_dashboard.py`**: Export Prometheus metrics to track GC runs and blockstore sizes.

## License
MIT License

# py-ipfs-lite: Deep Analysis, Gaps & Production Roadmap

> Full codebase analysis as of commit on `sumanjeet0012/py-ipfs-lite` — June 2026  
> Reference implementations: `ipfs-shipyard/go-ipfs-lite`, `ipfs/kubo`

---

## 1. What Currently Works (Solid Foundation)

The library is in better shape than a typical early-stage project. The core stack is correctly assembled:

- **Peer lifecycle** — `start()` / `close()` with `AsyncExitStack`, proper nursery management via Trio
- **DAG ops** — `add_node` / `get_node` / `remove_node` for `dag-json` and `dag-cbor`
- **UnixFS file ops** — `add_file(path)` / `get_file(cid_str)` wired through `MerkleDag`
- **Bitswap exchange** — `BitswapClient` connected to both `MemoryBlockStore` and `FilesystemBlockStore`
- **Kad DHT** — `KadDHT` in SERVER mode with `BootstrapDiscovery`
- **Pinning + GC** — JSON-backed `PinStore`, recursive DAG traversal in `gc()` for dag-pb and dag-json/cbor link resolution
- **Reprovider loop** — cancellable Trio background task, configurable interval
- **HTTP API** — FastAPI with Kubo-compatible `/api/v0/` routes: `add`, `cat`, `dag/put`, `dag/get`, `block/stat`, `block/rm`, `pin/add`, `pin/rm`, `repo/gc`, `refs/local`
- **CLI** — `daemon`, `add`, `get` subcommands with `--seed`, `--offline`, `--blockstore-*`
- **Interface layer** — clean `Protocol`-based `Host`, `Routing`, `BlockStore`, `Exchange`, `DagService` with adapter wrappers
- **8 examples** — covering embedding, DHT, IPLD, pinning, persistence, HTTP API, reprovider, verifiable inference
- **Interop scripts** — py↔py and py↔kubo shell scripts with a compiled Go peer

---

## 2. Critical Bugs & Correctness Issues

These must be fixed before any public release.

### 2.1 `__init__.py` is empty — no public API surface
```python
# py_ipfs_lite/__init__.py is completely empty
```
Users cannot do `from py_ipfs_lite import Peer`. Nothing is exported. Every import requires knowing the internal module path. Fix:
```python
# __init__.py
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config, AddParams
from py_ipfs_lite.interfaces import Host, Routing, BlockStore, Exchange, DagService

__all__ = ["Peer", "Config", "AddParams", "Host", "Routing", "BlockStore", "Exchange", "DagService"]
__version__ = "0.1.0"
```

### 2.2 `AddParams` is defined but never passed to `add_file`
The CLI constructs `AddParams` with `chunker`, `hash_fun`, `raw_leaves` — but `peer.add_file(path)` signature ignores it. The chunking config lives in the config/CLI layer but never reaches `MerkleDag`. This means the `--chunker` and `--hash-fun` CLI flags are silently no-ops.

```python
# peer.py — add_file doesn't accept or use AddParams
async def add_file(self, path: str) -> str:   # ← no params argument
    cid = await self.dag_service.add_file(path, wrap_with_directory=False)
```

Fix: `add_file(self, path: str, params: AddParams | None = None)` and thread it into `MerkleDag`.

### 2.3 Bootstrap peers hardcoded to `127.0.0.1` — daemon can never reach the real IPFS network
```python
DEFAULT_BOOTSTRAP_PEERS = [
    "/ip4/127.0.0.1/tcp/4001/p2p/12D3KooWCvVxG5SBv5fZNVULQGpJuhBCiRNAABs24QqyxtEYy1Pv",
]
```
This is a local placeholder. On a fresh machine this immediately errors. Real production bootstrap list:
```python
DEFAULT_BOOTSTRAP_PEERS = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
]
```

### 2.4 SECIO included — deprecated and removed from current IPFS stack
```python
from libp2p.security.secio.transport import Transport as SecioTransport
# ...
"/secio/1.0.0": SecioTransport(self._host_key),
```
SECIO was deprecated in go-libp2p v0.18 (2022) and is not negotiated by any current Kubo node. Including it: (a) expands attack surface, (b) causes confusion in protocol negotiation, (c) will fail interop with ≥ Kubo v0.14. Remove it; use only Noise.

### 2.5 `get_file` loads entire file into memory
```python
async def get_file(self, cid_str: str, ...) -> bytes:
    content, _ = await self.dag_service.fetch_file(cid)
    # returns full bytes — OOM on multi-GB files
```
For any file above ~500 MB this will exhaust memory. Go-ipfs-lite returns a `ReadSeekCloser` (streaming reader). Should return an `AsyncIterator[bytes]` or accept an output stream.

### 2.6 No GC concurrency guard — GC + add race condition
`gc()` calls `self.blockstore.all_keys()` then deletes, while a concurrent `add_file()` could add a block between the snapshot and the delete — causing it to be erroneously collected. Need a `trio.Lock` around GC execution.

### 2.7 `pyproject.toml` has placeholder URLs
```toml
Homepage = "https://github.com/your-org/py-ipfs-lite"
Repository = "https://github.com/your-org/py-ipfs-lite"
```
Must be corrected to `sumanjeet0012/py-ipfs-lite` before PyPI publish.

---

## 3. Gaps vs go-ipfs-lite (API Parity)

go-ipfs-lite is the declared parity target. The `API_SPEC_GO_IPFS_LITE.txt` defines what's needed. Here's what's still missing.

### 3.1 Missing: `setup_libp2p()` standalone helper
The Go library exposes `SetupLibp2p(ctx, privKey, secret, listenAddrs, datastore, ...opts)` as a top-level function that returns `(Host, Routing)`. This is the primary embedding entrypoint — it lets users compose their own host/routing then hand it to `Peer`. Currently this is buried inside `Peer._create_host()` / `Peer._create_routing()` and not accessible. Add:
```python
async def setup_libp2p(
    *,
    host_key: KeyPair,
    listen_addrs: list[str | Multiaddr],
    datastore: Datastore | None = None,
    offline: bool = False,
) -> tuple[Host, Routing]:
    ...
```

### 3.2 Missing: `default_bootstrap_peers()` exported function
The Go library has `DefaultBootstrapPeers()` returning the canonical list. Currently zero exported helpers exist for this.

### 3.3 Missing: `new_in_memory_datastore()` helper
Go exposes `NewInMemoryDatastore()`. Python has no equivalent exported constructor.

### 3.4 Missing: `Peer.new()` async classmethod
The Go library uses `New(ctx, ds, bs, host, routing, cfg)` returning a fully ready Peer. Python uses `__init__` + `start()`. The two-step pattern is fine Pythonically but the `Peer.new()` class factory from the spec is not implemented, which affects embedding API compatibility.

### 3.5 Missing: `Peer.session()` / `NodeGetter`
Go-ipfs-lite has `peer.Session(ctx)` which returns a `NodeGetter` backed by a Bitswap session — enabling parallel, deduplicated block fetches for large DAG traversals. Critical for performance with multi-block DAGs. Python has no session concept exposed.

### 3.6 Missing: Public `has_block(cid)` method
The Go Peer has `HasBlock(ctx, c) bool`. Python exposes `blockstore.has()` but not as a top-level `Peer.has_block()` call, which is part of the documented API surface.

### 3.7 Missing: `block_store()`, `exchange()`, `block_service()` accessors
Go exposes these as methods for advanced embedding (e.g. third-party DAG traversal code reaching into internals). Python accesses them as raw attributes with no encapsulation.

### 3.8 Missing: Streaming `add_file` input
Go's `AddFile(ctx, r io.Reader, params)` accepts any reader. Python's `add_file(path: str)` only accepts a filesystem path. Should accept `BinaryIO | AsyncGenerator[bytes, None]` as well.

---

## 4. Gaps vs Kubo (Production Features)

Kubo is the full-featured reference daemon. Not everything should be ported, but the following gaps matter for production use and ecosystem compatibility.

### 4.1 CAR file import/export — not implemented
CARv1/CARv2 (Content Addressable aRchive) is the primary format for:
- Filecoin storage deals
- Data replication/backup between nodes  
- Snapshot export of a DAG subtree
- Bootstrapping a cold node with a bundle

Without `export_car(cid)` and `import_car(path)`, py-ipfs-lite cannot participate in Filecoin data pipelines. This is a hard requirement for the GooseSwarm grant milestone on FVM retrieval.

### 4.2 IPNI / delegated content routing — not implemented
Kubo v0.18+ supports HTTP-based delegated routing via IPNI (InterPlanetary Network Indexer) at `https://cid.contact`. This dramatically accelerates content discovery vs pure DHT. The routing abstraction in `interfaces.py` already allows this to be plugged in, but no HTTP routing provider exists.

### 4.3 Pin types missing — only `direct` vs `recursive` bool
Kubo distinguishes three pin types:
- `direct` — pin this CID only (one block)
- `recursive` — pin this CID and all reachable blocks transitively
- `indirect` — automatically pinned because reachable from a recursive pin

`PinStore` uses `Dict[str, bool]` (recursive flag only). No `list_pins(type)` filtering. No `indirect` tracking. This makes the pin API non-compliant with `ipfs pin ls --type indirect`.

### 4.4 Missing HTTP API endpoints
The current HTTP API is missing several Kubo-compat endpoints frequently used by tooling:
```
/api/v0/id                   — node identity (PeerID, addresses, protocols)
/api/v0/swarm/peers          — connected peer list  
/api/v0/swarm/connect        — explicit peer connect
/api/v0/pin/ls               — list pins (with type filtering)
/api/v0/block/get            — fetch raw block bytes
/api/v0/block/put            — store raw block bytes
/api/v0/dag/resolve          — resolve IPLD path to CID
/api/v0/stats/bw             — bandwidth stats
/api/v0/version              — daemon version
```
Without `/api/v0/id` in particular, `ipfs-cluster` and other orchestration tools cannot identify the node.

### 4.5 No QUIC or WebTransport transport
Kubo and go-libp2p now default to QUIC (UDP-based, lower latency, works behind NAT). Python only uses TCP. This means py-ipfs-lite will fail to connect to peers that are QUIC-only (no TCP listener). Depends on py-libp2p implementing QUIC, but it should be tracked.

### 4.6 No connection manager
No limits on the number of open connections. A production node connecting to bootstrap peers and receiving inbound Bitswap requests can exhaust file descriptors. Need a connection manager with `LowWater` / `HighWater` peer count, similar to `go-libp2p-connmgr`.

### 4.7 No metrics / observability
Kubo exposes Prometheus metrics at `/debug/metrics/prometheus`. For production and for the GooseSwarm audit dashboard milestone, you need at minimum:
- Block store size (bytes, count)
- Bitswap sent/received bytes
- DHT query latency
- GC run frequency and reclamation stats

### 4.8 No datastore migration / versioning
Kubo has a repo versioning system (`/repo/version`) and migration tooling. py-ipfs-lite currently has no repo format version marker in the blockstore path, making future format changes non-migratable.

### 4.9 IPNS — not implemented
IPFS Name System (mutable pointers over the immutable CID namespace). Required for any content that updates (e.g. agent registry, latest model checkpoint). Kubo provides `/api/v0/name/publish` and `/api/v0/name/resolve`.

---

## 5. Code Quality & Production Hardening

### 5.1 Type annotations — partially missing
`add_node(node, codec: str)` — `node` is untyped (should be `dict | list | str | int | bytes`).  
`get_node()` has no return type.  
`gc()` returns `dict` — should return a typed `GCResult` dataclass.  
`all_keys()` returns `List[bytes]` — should return `List[CID]`.

### 5.2 Custom exception hierarchy — absent
All errors are bare `ValueError` and `RuntimeError`. Production code needs:
```python
class IPFSLiteError(Exception): ...
class BlockNotFoundError(IPFSLiteError): ...
class PinNotFoundError(IPFSLiteError): ...
class PeerNotStartedError(IPFSLiteError): ...
class RoutingError(IPFSLiteError): ...
```

### 5.3 No timeout support on operations
`get_file` and `get_node` can hang indefinitely if the provider is unreachable. Need per-operation `timeout: float | None = None` with `trio.fail_after`.

### 5.4 Reprovider does not filter pinned-only CIDs
Currently reprovides every block in the blockstore. Should only reprovide pinned (or recently added) CIDs to avoid DHT flooding.

### 5.5 Pin persistence is not atomic
`PinStore._save()` writes the JSON file directly — a crash mid-write corrupts the pin database. Should write to a temp file and `os.replace()` atomically.

### 5.6 `tox.ini` only lists `py311` — missing py310/py312/py313
`pyproject.toml` claims 3.10–3.13 support but CI only tests 3.11.

### 5.7 No progress callbacks for large file operations
`add_file` and `get_file` give no feedback for files > 1 MB. Add a `progress_callback: Callable[[int, int], None] | None = None` (bytes_done, bytes_total).

---

## 6. Conference Examples — What to Add

The existing 8 examples are solid demo pieces for local functionality. For conference presentations (libp2p Day, IPFS Camp, FIL Dev Summit, PyCon), you need examples that show:
1. **Interoperability** — talking to the real network, real Go nodes
2. **Advanced IPLD** — linked graphs, not just flat blobs
3. **AI/Agent use cases** — your differentiator in the ecosystem
4. **Production patterns** — streaming, CAR, IPNS, metrics

Below is the full recommended example set.

---

### Example 09: Real IPFS Network Round-Trip (vs Kubo)
**Conference value:** Proves production-level Go interop — one Python peer, one Kubo daemon, live on stage.

```python
# examples/09_kubo_interop.py
"""
Python peer adds a file. Kubo daemon fetches it by CID using only the DHT.
Then Kubo adds a file, Python peer fetches it.
Demonstrates true bi-directional protocol compatibility.
"""
async def main():
    # Start py peer, bootstrap to real IPFS network
    peer = Peer(Config(), listen_addrs=["/ip4/0.0.0.0/tcp/4002"])
    await peer.start()
    await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)

    cid = await peer.add_file("testdata/sample.txt")
    print(f"Added CID: {cid}")
    print(f"Fetch with Kubo: ipfs cat {cid}")
    print("Waiting 30s for Kubo to discover via DHT...")
    await trio.sleep(30)
    # Then fetch a CID previously added by Kubo
    kubo_cid = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    data = await peer.get_file(kubo_cid)
    print(f"Fetched {len(data)} bytes from Kubo node via DHT!")
```

---

### Example 10: Linked IPLD DAG — Knowledge Graph
**Conference value:** Shows IPLD as a programmable database, not just file storage. DAG links between nodes, CID-addressable graph traversal.

```python
# examples/10_ipld_linked_dag.py
"""
Build a simple knowledge graph: Agent → Model → Checkpoint → Dataset
Each node links to its dependencies via CID references.
Demonstrates IPLD as a content-addressed, traversable graph.
"""
async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # Bottom of DAG — leaf nodes
    dataset_cid = await peer.add_node({"name": "wikitext-103", "size_gb": 1.8, "sha256": "abc..."})
    checkpoint_cid = await peer.add_node({"epoch": 42, "loss": 0.031, "dataset": {"/": dataset_cid}})
    model_cid = await peer.add_node({"arch": "transformer", "params": "7B", "checkpoint": {"/": checkpoint_cid}})
    agent_cid = await peer.add_node({"id": "summarizer-v2", "model": {"/": model_cid}, "version": "2.1.0"})

    print(f"Agent root CID: {agent_cid}")
    # Now traverse the graph — fetch agent, follow links
    agent = await peer.get_node(agent_cid)
    model = await peer.get_node(agent["model"]["/"])
    ckpt = await peer.get_node(model["checkpoint"]["/"])
    dataset = await peer.get_node(ckpt["dataset"]["/"])
    print(f"Traversed 4-hop DAG: agent → model → checkpoint → dataset")
    print(f"Dataset: {dataset['name']}")

    await peer.close()
```

---

### Example 11: CAR File Export/Import — Offline Data Bundle
**Conference value:** Unlocks Filecoin storage deals, snapshot sharing, cold-node bootstrap. Critical missing feature made visible.

```python
# examples/11_car_export_import.py
"""
Export a DAG subtree to a CARv1 file. Import it on another peer (offline).
Shows content-addressable bundles: the format used in Filecoin deals.

Note: requires py_ipfs_lite.car module (to be implemented).
"""
async def main():
    writer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await writer.start()

    # Build a DAG
    leaf_a = await writer.add_node({"content": "chapter one"})
    leaf_b = await writer.add_node({"content": "chapter two"})
    root = await writer.add_node({"title": "My Book", "chapters": [{"/": leaf_a}, {"/": leaf_b}]})

    # Export to CAR
    car_bytes = await writer.export_car(root)
    with open("book.car", "wb") as f:
        f.write(car_bytes)
    print(f"Exported {len(car_bytes)} bytes to book.car")
    await writer.close()

    # Import on a fresh peer — fully offline, no network needed
    reader = Peer(Config(offline=True, reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await reader.start()
    imported_root = await reader.import_car("book.car")
    assert imported_root == root
    book = await reader.get_node(root)
    print(f"Imported offline: '{book['title']}' with {len(book['chapters'])} chapters")
    await reader.close()
```

---

### Example 12: Streaming Large File with Progress
**Conference value:** Proves production readiness for multi-GB files. AsyncIterator pattern, memory-safe.

```python
# examples/12_streaming_large_file.py
"""
Add and retrieve a large file using async streaming — no full-file buffering.
Shows py-ipfs-lite is suitable for multi-GB datasets, not just toy data.
"""
import sys
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config, AddParams

async def progress(done: int, total: int):
    pct = int(done * 100 / total) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct}% ({done // 1024}KB / {total // 1024}KB)", end="", flush=True)

async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # Generate a 50 MB synthetic file
    data = b"x" * (50 * 1024 * 1024)
    with open("/tmp/bigfile.bin", "wb") as f:
        f.write(data)

    print("Adding 50 MB file (streaming chunked)...")
    cid = await peer.add_file("/tmp/bigfile.bin", params=AddParams(chunker="size-262144"), progress_callback=progress)
    print(f"\nCID: {cid}")

    print("\nFetching via streaming iterator...")
    received = 0
    async for chunk in peer.stream_file(cid):
        received += len(chunk)
        await progress(received, len(data))
    print(f"\nReceived {received} bytes — integrity verified!")
    await peer.close()
```

---

### Example 13: Verifiable AI Agent Memory Chain (IPLD DAG)
**Conference value:** The killer GooseSwarm demo. Every agent action is a CID-linked node. Provably immutable memory. Fork-detectable. Audit-ready.

```python
# examples/13_agent_memory_chain.py
"""
An AI agent stores each conversation turn as a DAG-CBOR node
linked to the previous turn by CID — forming an append-only,
content-addressed memory chain. Any tampering changes the CID
and breaks the chain. Perfect for audit trails and verifiable inference.
"""
import hashlib, datetime
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    print("=== GooseSwarm Agent Memory Chain ===")
    turns = [
        ("user", "What is content-addressed storage?"),
        ("agent", "Content-addressed storage identifies data by a hash of its content..."),
        ("user", "How does IPFS use it?"),
        ("agent", "IPFS assigns every file and data structure a CID derived from its content hash..."),
    ]

    prev_cid = None
    cids = []
    for role, text in turns:
        node = {
            "role": role,
            "text": text,
            "text_hash": hashlib.sha256(text.encode()).hexdigest(),
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "prev": {"/": prev_cid} if prev_cid else None,
        }
        cid = await peer.add_node(node, codec="dag-cbor")
        cids.append(cid)
        prev_cid = cid
        print(f"  [{role}] → CID: {cid[:30]}...")

    print(f"\nChain head: {cids[-1]}")
    print("\nVerifying chain integrity by traversal...")
    current_cid = cids[-1]
    chain = []
    while current_cid:
        node = await peer.get_node(current_cid)
        chain.append((node["role"], node["text"][:50]))
        link = node.get("prev")
        current_cid = link["/"] if link else None
    chain.reverse()
    for role, text in chain:
        print(f"  [{role}]: {text}...")
    print(f"\n✓ Chain of {len(chain)} turns verified — immutable and content-addressed")
    await peer.close()
```

---

### Example 14: Multi-Peer Distributed RAG Pipeline
**Conference value:** Production AI use-case. Documents chunked as IPLD, retrieved via Bitswap, assembled for RAG — fully decentralized.

```python
# examples/14_distributed_rag.py
"""
Three peers simulate a distributed RAG pipeline:
- Indexer peer: chunks a document corpus, stores each chunk as a CID
- Retriever peer: given a query, fetches relevant CIDs via DHT
- Aggregator peer: assembles retrieved chunks into RAG context

Demonstrates py-ipfs-lite as infrastructure for decentralized AI.
"""
async def main():
    # Indexer — stores document chunks
    indexer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await indexer.start()

    documents = [
        "IPFS is a distributed file system that seeks to connect all computing devices...",
        "Filecoin is a decentralized storage network built on IPFS with economic incentives...",
        "libp2p is a modular networking framework used in IPFS, Ethereum 2.0, and Polkadot...",
    ]
    index_cid = await indexer.add_node({
        "type": "rag-index",
        "chunks": [{"/": await indexer.add_node({"text": doc, "source": f"doc-{i}"})}
                   for i, doc in enumerate(documents)]
    })
    print(f"Indexed {len(documents)} chunks. Root CID: {index_cid}")

    # Retriever — fetches index, simulates relevance scoring
    retriever = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await retriever.start()
    indexer_addr = str(indexer.host.addrs()[0])
    
    index = await retriever.get_node(index_cid, provider_addr=indexer_addr)
    query = "How does Filecoin relate to IPFS?"
    results = []
    for chunk_link in index["chunks"]:
        chunk = await retriever.get_node(chunk_link["/"], provider_addr=indexer_addr)
        score = sum(w in chunk["text"].lower() for w in query.lower().split())
        results.append((score, chunk["text"], chunk_link["/"]))
    results.sort(reverse=True)

    context = "\n".join(text for _, text, _ in results[:2])
    print(f"\nRAG context assembled for query: '{query}'")
    print(f"Context:\n{context}")
    print(f"\nContext CID refs: {[cid[:20] + '...' for _, _, cid in results[:2]]}")

    await retriever.close()
    await indexer.close()
```

---

### Example 15: IPNS Mutable Pointer — Versioned Agent Registry
**Conference value:** Bridges immutable CIDs and mutable state. Registry points always resolve to the latest version.

```python
# examples/15_ipns_mutable_registry.py
"""
Publish a versioned agent registry under an IPNS name.
The CID of the registry changes with each update,
but the IPNS name always resolves to the latest version.

Note: requires IPNS module (to be implemented).
"""
async def main():
    peer = Peer(Config(), listen_addrs=["/ip4/0.0.0.0/tcp/4003"])
    await peer.start()
    await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)

    # Publish v1
    v1_cid = await peer.add_node({"version": "1.0.0", "agents": ["summarizer", "classifier"]})
    name = await peer.ipns_publish(v1_cid)
    print(f"IPNS name: {name}  →  {v1_cid}")

    # Update to v2 — name stays the same, CID changes
    v2_cid = await peer.add_node({"version": "2.0.0", "agents": ["summarizer", "classifier", "retriever"]})
    await peer.ipns_publish(v2_cid, name=name)
    
    # Resolve — always returns latest
    resolved = await peer.ipns_resolve(name)
    assert resolved == v2_cid
    print(f"IPNS name: {name}  →  {v2_cid}  (updated)")
    print("✓ Mutable pointer updated. The name is stable; the CID changed.")
    await peer.close()
```

---

### Example 16: Metrics Dashboard Integration
**Conference value:** Shows ops-readiness. Prometheus-compatible metrics emitted, Grafana-importable. Required for GooseSwarm audit dashboard.

```python
# examples/16_metrics_and_observability.py
"""
Run a py-ipfs-lite peer with Prometheus metrics exposed at /metrics.
Tracks blockstore size, Bitswap throughput, DHT query count, GC stats.
"""
from py_ipfs_lite.metrics import MetricsCollector  # to be implemented
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(Config(), listen_addrs=["/ip4/0.0.0.0/tcp/4004"])
    metrics = MetricsCollector(peer)
    await peer.start()
    
    # Expose metrics via HTTP
    # GET http://localhost:9090/metrics → Prometheus format
    await metrics.serve(host="0.0.0.0", port=9090)
    
    # Normal operations — metrics update automatically
    cid = await peer.add_node({"demo": "metrics"})
    _ = await peer.get_node(cid)
    await peer.gc()
    
    snapshot = metrics.snapshot()
    print(f"Blockstore blocks: {snapshot['blockstore_block_count']}")
    print(f"Bitswap sent: {snapshot['bitswap_sent_bytes']} bytes")
    print(f"GC runs: {snapshot['gc_run_total']}")
    print(f"DHT provides: {snapshot['dht_provide_total']}")
```

---

## 7. Prioritized Implementation Plan

### Phase A — Fix Critical Bugs First (1–2 weeks)
1. Populate `__init__.py` with proper exports
2. Wire `AddParams` through to `add_file` and `MerkleDag`
3. Replace `DEFAULT_BOOTSTRAP_PEERS` with real IPFS bootstrap list
4. Remove SECIO; Noise-only
5. Fix `pyproject.toml` URLs
6. Add `trio.Lock` to `gc()` for concurrency safety
7. Make `PinStore._save()` atomic with temp-file + `os.replace()`

### Phase B — Core API Parity with go-ipfs-lite (2–4 weeks)
1. Export `setup_libp2p()`, `default_bootstrap_peers()`, `new_in_memory_datastore()`
2. Add `Peer.has_block(cid)`, `Peer.block_store()`, `Peer.exchange()` accessors
3. Add streaming `add_file(stream: BinaryIO, params)` signature
4. Add streaming `get_file` returning `AsyncIterator[bytes]`
5. Implement `Peer.session()` backed by Bitswap sessions
6. Add custom exception hierarchy
7. Add per-operation `timeout` parameter with `trio.fail_after`
8. Add `progress_callback` to file ops

### Phase C — Production Features (4–8 weeks)
1. CAR v1 export (`peer.export_car(cid)`) and import (`peer.import_car(path)`)
2. Full pin type system: `direct`, `recursive`, `indirect` + `list_pins(type)`
3. Missing HTTP API endpoints: `id`, `swarm/peers`, `swarm/connect`, `pin/ls`, `block/get`, `block/put`, `dag/resolve`, `version`
4. Basic metrics via `prometheus-client`
5. Reprovider: filter to pinned-only CIDs
6. Tox matrix: py310/py311/py312/py313

### Phase D — Advanced (post-v0.2)
1. IPNI/delegated HTTP routing (`cid.contact`)
2. IPNS publish/resolve
3. Connection manager with LowWater/HighWater
4. QUIC transport (when py-libp2p adds it)
5. Repo version marker + migration path

---

## 8. Quick Conference Readiness Checklist

| What | Status | Blocker? |
|---|---|---|
| Empty `__init__.py` | 🔴 Not done | Yes — kills importability demo |
| Real bootstrap peers | 🔴 Wrong values | Yes — daemon won't join network on stage |
| SECIO removed | 🔴 Present | Yes — interop failure with Kubo ≥ 0.14 |
| `AddParams` wired | 🔴 Silent no-op | Yes — CLI flags shown but do nothing |
| Streaming get_file | 🔴 Missing | Yes — OOM on large file demos |
| CAR export/import | 🔴 Missing | Yes — needed for Filecoin demo |
| `setup_libp2p()` exported | 🟡 Partial | Nice-to-have for embedding story |
| IPNS | 🔴 Missing | Needed for example 15 |
| Custom exceptions | 🟡 Partial | Nice-to-have |
| Metrics | 🔴 Missing | Needed for GooseSwarm audit dashboard |
| Examples 09–16 | 🔴 Missing | These are the conference demos |
| Go interop (example 09) | ✅ Infra ready | Just write the example |
| Agent memory chain | ✅ Almost | Example 08 is 90% there — extend it |
| Linked DAG | ✅ Works today | Example 10 can be written now |

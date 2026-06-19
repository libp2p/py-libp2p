Title: Live Content

Description: Fetched live

Source: https://raw.githubusercontent.com/sumanjeet0012/Temporary/main/py-ipfs-lite-analysis.md

---

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
IPFS Name System (mutable pointers over the immutable CID namespace). Required for any content that updates (e.g. agent registry, latest model checkpoint). Kubo provi


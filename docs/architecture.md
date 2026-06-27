# Architecture

This document describes how `py-ipfs-lite` is structured internally: what the components are,
how they relate to each other, and why certain design decisions were made. It is the right
starting point if you want to contribute, swap out a subsystem, or just understand what is
happening under the hood when you call `peer.add_file()`.

______________________________________________________________________

## 1. Component Overview

The central object in `py-ipfs-lite` is the `Peer` class, defined in
[`py_ipfs_lite/peer.py`](../py_ipfs_lite/peer.py). It is the public API surface — everything
a user or embedding application interacts with goes through `Peer`.

`Peer` orchestrates **five subsystems**, each defined as a `Protocol` interface in
[`py_ipfs_lite/interfaces.py`](../py_ipfs_lite/interfaces.py):

| Interface    | Responsibility                                       | Default implementation                                                    |
| ------------ | ---------------------------------------------------- | ------------------------------------------------------------------------- |
| `Host`       | libp2p network layer: identity, connections, streams | `HostAdapter` wrapping py-libp2p's `BasicHost`                            |
| `Routing`    | Content discovery and DHT / IPNI interaction         | `TieredRouting` (\[DHT + IPNI\]) or bare `RoutingAdapter`                 |
| `BlockStore` | Persistent or in-memory raw block storage            | `BlockStoreAdapter` wrapping `FilesystemBlockStore` or `MemoryBlockStore` |
| `Exchange`   | Bitswap: fetching blocks from remote peers           | `ExchangeAdapter` wrapping py-libp2p's `BitswapClient`                    |
| `DagService` | DAG construction and traversal                       | py-libp2p's `MerkleDag`                                                   |

Additionally, two service objects run alongside `Peer`:

| Object       | Responsibility                                                             |
| ------------ | -------------------------------------------------------------------------- |
| `PinStore`   | Tracks pinned CIDs; controls what GC is allowed to delete                  |
| `Reprovider` | Background task that periodically re-announces all local blocks to the DHT |

```
┌──────────────────────────────────────────────────────────┐
│                         Peer                             │
│                                                          │
│   ┌──────────┐  ┌──────────┐  ┌───────────┐             │
│   │   Host   │  │ Routing  │  │BlockStore │             │
│   │ Adapter  │  │(Tiered)  │  │ Adapter   │             │
│   └────┬─────┘  └────┬─────┘  └─────┬─────┘            │
│        │             │              │                    │
│   ┌────┴─────┐  ┌────┴──────┐  ┌───┴──────────┐        │
│   │py-libp2p │  │ KadDHT +  │  │ MetricsBlock │        │
│   │BasicHost │  │DelegatedH │  │ Store + FS / │        │
│   │(Noise)   │  │TTPRouting │  │ Memory store │        │
│   └──────────┘  └───────────┘  └──────────────┘        │
│                                                          │
│   ┌──────────────────┐   ┌─────────────────┐            │
│   │ ExchangeAdapter  │   │   DagService    │            │
│   │  (BitswapClient) │   │  (MerkleDag)   │            │
│   └──────────────────┘   └─────────────────┘            │
│                                                          │
│   ┌──────────┐   ┌────────────┐   ┌──────────────────┐  │
│   │PinStore  │   │Reprovider  │   │  RWLock (GC)     │  │
│   └──────────┘   └────────────┘   └──────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

______________________________________________________________________

## 2. The Adapter Pattern

`py-ipfs-lite` defines its five core interfaces as Python `Protocol` classes. This is an explicit
design seam between `py-ipfs-lite`'s own API and the concrete types provided by `py-libp2p`.

The reason this matters: py-libp2p uses slightly different method names from what
`py-ipfs-lite` expects. For example:

- py-libp2p's `BasicHost` exposes `.get_id()` and `.get_addrs()`
- `py-ipfs-lite`'s `Host` interface expects `.id()` and `.addrs()`
- py-libp2p's blockstore exposes `.put_block()` / `.get_block()`
- `py-ipfs-lite`'s `BlockStore` interface expects `.put()` / `.get()`

Rather than forking py-libp2p or patching it, `py-ipfs-lite` uses three **adapter classes**
in `interfaces.py` to bridge the gap:

| Adapter             | Wraps                                        | Translates                                                                       |
| ------------------- | -------------------------------------------- | -------------------------------------------------------------------------------- |
| `HostAdapter`       | `BasicHost`                                  | `get_id()` → `id()`, `get_addrs()` → `addrs()`, `new_stream()` → `open_stream()` |
| `BlockStoreAdapter` | `MemoryBlockStore` or `FilesystemBlockStore` | `put_block()` → `put()`, `get_block()` → `get()`, etc.                           |
| `RoutingAdapter`    | `KadDHT`                                     | Wraps DHT calls and instruments them with Prometheus timing                      |

**What this buys you:** You can swap out any subsystem by providing a different implementation
that satisfies the `Protocol` interface, without changing `Peer`. For example:

```python
# Bring your own blockstore
from py_ipfs_lite.interfaces import BlockStore

class RedisBlockStore:
    async def put(self, cid: bytes, data: bytes) -> None: ...
    async def get(self, cid: bytes) -> bytes | None: ...
    # ... etc

peer = Peer(config, blockstore=RedisBlockStore())
```

All five interfaces (`Host`, `Routing`, `BlockStore`, `Exchange`, `DagService`) are injectable
through `Peer.__init__`. Only those left as `None` will be auto-constructed during `peer.start()`.

______________________________________________________________________

## 3. Data Flow: Adding a File

When you call `await peer.add_file("/path/to/file.txt")`, the following sequence occurs:

```
add_file(path)
    │
    ├── Acquire RWLock (read lock) ──────────────────────────────────────┐
    │   (allows concurrent adds; blocks only if GC is running)           │
    │                                                                    │
    ├── dag_service.add_file(path)                                       │
    │       │                                                            │
    │       ├── MerkleDag reads file from disk (synchronous I/O)        │
    │       ├── Chunks file into blocks (default: 262144 bytes/chunk)   │
    │       ├── Constructs UnixFS DAG-PB nodes for each chunk           │
    │       ├── Computes CIDv1 for each block                           │
    │       └── Writes each block to BlockStore via Exchange.notify()   │
    │                                                                    │
    ├── Release RWLock ───────────────────────────────────────────────────┘
    │
    ├── Format root CID as a base32 CIDv1 string
    │
    └── routing.provide(cid_str)
            │
            ├── TieredRouting fans out to:
            │       ├── DelegatedHTTPRouting.provide()
            │       │     └── HTTP PUT /routing/v1/providers/{cid} → cid.contact (IPIP-337)
            │       └── RoutingAdapter.provide()
            │             └── KadDHT.provide() → announces to DHT peers
            │
            └── Returns CID string to caller
```

> **Honest caveat:** `MerkleDag.add_file()` in py-libp2p performs a blocking `open(path, "rb").read()`
> with no `await` checkpoint inside the chunking/hashing loop. Because Trio uses cooperative
> concurrency, CPU-bound work with no yield points cannot actually interleave with other tasks
> regardless of how fine-grained the `RWLock` is. The `RWLock` correctly guarantees
> **safety** (no concurrent GC corruption), but **throughput** for concurrent large-file
> ingestion is limited by this upstream behaviour. See the
> [Observability guide](./guides/observability.md) for a concrete benchmark.

______________________________________________________________________

## 4. Data Flow: Fetching Content

When you call `await peer.get_file(cid_str)`, the sequence is:

```
get_file(cid_str)
    │
    ├── If provider_addr provided: host.connect(provider_addr) directly
    │
    ├── Else if routing is available:
    │       └── routing.find_providers(cid_str)
    │               ├── TieredRouting queries IPNI first (HTTP GET /routing/v1/providers/{cid})
    │               └── Falls back to KadDHT.find_providers()
    │           For each provider found: host.connect(provider)
    │
    ├── parse_cid(cid_str)  →  raw CID bytes
    │
    └── fetch_stream(cid) [async generator]
            │
            ├── fetch_block_with_timeout(cid)
            │       └── exchange.get_block(cid)
            │               └── BitswapClient sends WANT message to connected peers
            │                   Receives block data back via Bitswap protocol
            │
            ├── Detect codec from CID prefix (dag-pb, dag-json, dag-cbor, raw)
            │
            ├── If dag-pb (UnixFS):
            │       ├── decode_dag_pb(data) → links + UnixFS data
            │       ├── If directory: recurse into first link
            │       └── If chunked file: yield each chunk's data in order
            │
            └── If raw / other codec: yield data directly

        stream=False (default): buffer all chunks → return bytes
        stream=True:            return the async generator directly
        output_path provided:   write chunks to file, return None
```

______________________________________________________________________

## 5. Concurrency Model

`py-ipfs-lite` uses [Trio](https://trio.readthedocs.io/) as its async runtime. This is a
deliberate choice inherited from py-libp2p — Trio's structured concurrency model and
cancellation semantics are a better fit for a networked peer than `asyncio`.

### The RWLock

The critical invariant for GC correctness is: **a block must not be deleted while it is
being written**. The original implementation used a single `trio.Lock`, which serialized
all `add_file`, `add_node`, and `gc()` calls.

The current implementation uses a custom `RWLock` (reader-writer lock) defined in `peer.py`:

- **Read lock** (`async with self._gc_lock.read_lock()`): taken by `add_file()` and `add_node()`.
  Multiple read locks can be held simultaneously — concurrent ingestion tasks do not block
  each other.
- **Write lock** (`async with self._gc_lock.write_lock()`): taken exclusively by `gc()`.
  The write lock waits until all active readers have finished, then blocks new readers from
  starting until GC is complete.

```python
# Multiple adds can run concurrently
async with self._gc_lock.read_lock():
    await self.blockstore.put(cid, data)

# GC gets exclusive access — waits for all readers first
async with self._gc_lock.write_lock():
    to_delete = all_cids - reachable_cids
    for cid in to_delete:
        await self.blockstore.delete(cid)
```

### The `get_file` cancel-scope fix

Trio requires that `trio.fail_after()` cancel scopes must not span an `async for` yield
boundary inside an async generator. The original implementation violated this, causing
nursery corruption under timeout. The fix isolates the cancel scope:

```python
# cancel scope opens and FULLY CLOSES before the yield
async def fetch_block_with_timeout(current_cid):
    with trio.fail_after(t_val):
        return await self._exchange.get_block(current_cid)

async def fetch_stream(current_cid):
    data = await fetch_block_with_timeout(current_cid)  # scope is gone by here
    ...
    yield data  # safe: no cancel scope is open across this yield
```

### Background tasks

`peer.start()` opens a `trio.Nursery` and starts two long-running background tasks:

- `reprovider.start()` — loops every `reprovide_interval_seconds` (default: 43200s / 12h),
  re-announcing all pinned blocks to the DHT and IPNI.
- `_periodic_pruner_task()` — triggers `ConnectionPruner.maybe_prune_connections()` every 15
  seconds to enforce the `conn_mgr_high_water` / `conn_mgr_low_water` connection limits.

______________________________________________________________________

## 6. The IPNS Trust Model

IPNS (InterPlanetary Name System) maps a `PeerID` (a stable identifier) to a mutable value
(typically an IPFS CID path like `/ipfs/bafy...`). Records are stored in the DHT and signed
by the publisher's private key.

### What is verified on `resolve_name()`

When `peer.resolve_name(peer_id_str)` is called, `py-ipfs-lite` runs a full cryptographic
validation chain in `validate_ipns_record()` (in `py_ipfs_lite/ipns.py`):

1. **Public key verification:** The public key embedded in the record must hash to exactly
   the expected `PeerID`. A record signed by any other key — even a structurally valid one —
   is rejected with `RoutingError("IPNS record pubKey does not match the expected Peer ID")`.

1. **Signature verification (V2 preferred):** If the record contains a V2 signature (the
   current standard), the signed CBOR payload must match both the declared `value` and
   `validity` fields byte-for-byte. This prevents a partial-substitution forgery attack.
   V1 (legacy) signature verification is also supported as fallback.

1. **Expiry verification:** The `validity` field is a RFC-3339 timestamp. If the current
   UTC time is past this timestamp, the record is rejected with
   `RoutingError("IPNS record has expired")`.

### What is NOT verified

- **IPNI announce-side trust:** When a peer calls `routing.provide(cid)`, the IPNI indexer
  (`cid.contact`) accepts the announcement without verifying that the announcing peer actually
  has the content. This is a property of the IPNI protocol, not a py-ipfs-lite limitation.
  Do not treat an IPNI provider result as a guarantee of content availability.

- **DHT peer identity for IPNS records:** The DHT guarantees that a record stored at key
  `/ipns/{peerID}` was PUT by some peer, but does not guarantee *which* peer. The
  `validate_ipns_record()` signature check is what closes this gap — a forged record PUT
  into the DHT by a malicious peer will be rejected at validation time.

______________________________________________________________________

## 7. Where py-libp2p Ends and py-ipfs-lite Begins

Understanding the boundary helps contributors decide where a fix belongs.

**py-libp2p's responsibility (do not change here):**

- TCP/QUIC transport
- Noise handshake and channel encryption
- Yamux stream multiplexing
- KadDHT implementation
- Bitswap protocol (WANT/HAVE/BLOCK message exchange)
- `MerkleDag.add_file()` chunking and UnixFS DAG construction
- `MemoryBlockStore` and `FilesystemBlockStore`

**py-ipfs-lite's responsibility:**

- The `Peer` orchestrator and its lifecycle (`start()`, `close()`)
- The adapter layer (`HostAdapter`, `BlockStoreAdapter`, `RoutingAdapter`)
- The `TieredRouting` and `DelegatedHTTPRouting` for IPNI (IPIP-337)
- The `RWLock` concurrency model for GC safety
- The `PinStore` and GC logic (mark-and-sweep over the blockstore)
- The IPNS publish/resolve/validate logic (including V2 cryptographic verification)
- The CAR v1 export/import with async I/O (`trio.open_file`)
- The Prometheus metrics instrumentation layer (`MetricsBlockStore`, `RoutingAdapter`)
- The HTTP API (`api.py`) and CLI (`cli.py`)

If a bug is in the Bitswap wire protocol, it belongs in py-libp2p. If a bug is in how
blocks are pinned, GC'd, announced, or served over HTTP, it belongs here.

> **Note on upstream contributions:** The Bitswap improvements for Kubo compatibility
> (including dag-pb/cbor/json codec negotiation) were developed as part of this project and
> merged into the canonical `libp2p/py-libp2p` repository via
> [PR #1321](https://github.com/libp2p/py-libp2p/pull/1321). This means the interoperability
> work is now part of the reference Python libp2p implementation.

# Comparison: py-ipfs-lite vs go-ipfs-lite vs Kubo

`py-ipfs-lite` is designed to sit cleanly between a raw libp2p stack and a full IPFS daemon.

- **vs `go-ipfs-lite`**: It is a direct Python port. It shares the same API philosophy (an embeddable `Peer` struct that orchestrates Host, Routing, BlockStore, Exchange, and DagService) and supports the exact same feature set, plus IPNI and Prometheus metrics.
- **vs Kubo**: Kubo is a heavy, standalone daemon designed to run infrastructure. `py-ipfs-lite` is an embeddable library designed to bring IPFS capabilities directly into Python applications (like AI agents or RAG pipelines) without requiring users to install and manage a separate Kubo process. `py-ipfs-lite` also ships an optional Kubo-compatible HTTP API to act as a lightweight drop-in replacement for basic use cases.

______________________________________________________________________

## Feature Matrix

| Feature                    |       `py-ipfs-lite`        |       `go-ipfs-lite`        |  Kubo  | Notes                                                                            |
| -------------------------- | :-------------------------: | :-------------------------: | :----: | -------------------------------------------------------------------------------- |
| **Core Architecture**      |         Embeddable          |         Embeddable          | Daemon |                                                                                  |
| **Bitswap**                |             ✅              |             ✅              |   ✅   | Fully interoperable                                                              |
| **UnixFS (add/get file)**  |             ✅              |             ✅              |   ✅   | `py-ipfs-lite` supports 256KB chunking & DAG-PB                                  |
| **DAG Codecs**             |     DAG-JSON, DAG-CBOR      |     DAG-JSON, DAG-CBOR      |  All   |                                                                                  |
| **Pinning**                | Direct, Recursive, Indirect | Direct, Recursive, Indirect |  All   |                                                                                  |
| **Garbage Collection**     |             ✅              |             ✅              |   ✅   | Atomic RWLock in Python version                                                  |
| **IPNS**                   |   ✅ (Publish & Resolve)    |             ✅              |   ✅   | Verified signatures and expiry                                                   |
| **IPNI (`cid.contact`)**   |             ✅              |             ❌              |   ✅   | Python version supports IPNI via `TieredRouting` (resolve and announce)          |
| **CAR File Export/Import** |         ✅ (CARv1)          |             ❌              |   ✅   | Filecoin-compatible CARv1 export                                                 |
| **Prometheus Metrics**     |             ✅              |             ❌              |   ✅   |                                                                                  |
| **Connection Manager**     |             ✅              |             ✅              |   ✅   | High/Low watermarks prune connections                                            |
| **Transport**              |         TCP, Noise          |      TCP, Noise, QUIC       |  All   | QUIC ships in `py-libp2p`; not yet wired into `py-ipfs-lite`'s host construction |
| **HTTP API**               |         ✅ (Subset)         |             ❌              |   ✅   | Python version wraps a Kubo-compatible `/api/v0/`                                |

______________________________________________________________________

## What is intentionally out of scope

To keep the library "lite" and maintainable, a few complex Kubo features are explicitly excluded by design:

### 1. Full CARv2 Support

`py-ipfs-lite` exports **CARv1** archives. CARv2 adds a random-access index section that is complex to generate. Most tools (including `lotus client import --car`) accept CARv1 without issue. `import_car()` handles both versions on input, but we only export CARv1.

### 2. Repo Migration Tooling

Kubo has a complex migration system (`fs-repo-migrations`) because it updates its on-disk data structures over time. `py-ipfs-lite` uses a simple filesystem layout where the CID is the filename. We do not intend to change this format, so we do not ship migration tooling.

### 3. MFS (Mutable File System)

MFS provides a virtual directory tree (`/api/v0/files/...`). This requires a lot of state management and overhead. If you need mutable directories, use IPNS pointers to updated directory DAGs instead.

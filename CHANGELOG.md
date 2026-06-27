# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## \[Unreleased\]

### Added

- **IPNS**: Added mutable pointer support (publish and resolve).
- **IPNI**: `TieredRouting` added to seamlessly query `cid.contact` alongside the Kademlia DHT.
- **CAR Files**: Added `import_car` and `export_car` for CARv1 archives, enabling Filecoin storage pipelines.
- **Metrics**: Added Prometheus metrics exposed at `/debug/metrics/prometheus`.
- **HTTP API**: Built a Kubo-compatible `/api/v0/` daemon wrapping core functionality.

### Changed

- **Concurrency**: Replaced the global `trio.Lock` with a granular `RWLock`. Concurrent `add_file` and `get_file` calls (readers) now safely run in parallel, while Garbage Collection (writer) takes exclusive access.
- **Connection Manager**: Wired `conn_mgr_high_water` and `conn_mgr_low_water` into the libp2p host to prevent file descriptor exhaustion in long-running daemons.

### Fixed

- **IPNS Security**: Fixed missing validation in IPNS resolution. Forged records with mismatched PeerIDs or invalid signatures are now correctly rejected.
- **CAR I/O**: Switched CAR export from synchronous blocking file I/O to async I/O via `trio`, preventing event loop stalls on large files.
- **Async Iterators**: Fixed `get_file(stream=True)` to correctly return an `AsyncIterator[bytes]` and prevent async loop blocking bugs.

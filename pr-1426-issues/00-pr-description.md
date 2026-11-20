## Description

This PR fixes the issues documented in **#1425** (Kademlia DHT), **#1450** (Bitswap), **#1451** (Network & Swarm), and **#1452** (QUIC), along with additional correctness, robustness, and performance fixes across the networking stack. It brings the DHT implementation closer to the IPFS DHT specification and libp2p Kademlia spec, and resolves memory leaks, CPU busy-spins, and connection-management bugs found while running the node against the public network.

## Issues Fixed

### Kademlia DHT (`libp2p/kad_dht/`) — closes #1425

**Critical**
- `timeReceived` now uses RFC3339Nano format per spec (was Unix epoch float), with backward-compatible parsing of both formats.
- `clean_record()` strips `timeReceived` from incoming records to prevent timestamp forgery.
- PUT_VALUE stream is reset on validation/storage failure per spec ("on any error, the stream is reset") instead of closed gracefully.
- PUT_VALUE records capped at 1 MB (`MAX_RECORD_SIZE`).
- Value store LRU eviction at 50K entries (`MAX_VALUE_STORE_SIZE`) to prevent OOM.

**Spec compliance**
- ADD_PROVIDER: receiver echoes the request per spec; key length capped at 80 bytes; per-peer rate limit (10 msgs / 10s window); max 20 provider records per message.
- FIND_NODE key validated as a valid multihash.
- GET_VALUE: 128-byte max key size; records signature-validated before serving; closer-peer addresses stored in the peerbook.
- Connection type now reports dynamically (CONNECTED / CAN_CONNECT / NOT_CONNECTED) instead of always CONNECTED.

**Provider system**
- Iterative provider discovery using closer peers from responses (was single-shot).
- Provider records republished every 22 hours per spec.
- Providers per key capped at k=20.
- Provider keys validated for multihash structure.
- JSON persistence for `ProviderStore` via `persist_dir`.

**Value store**
- Value records republished every 22 hours.
- LRU eviction (50K) prevents OOM.
- JSON persistence for `ValueStore` via `persist_dir`.
- Closer-peer addresses stored in peerbook when processing GET_VALUE responses.

**Peer routing**
- Iterative lookup continues while unqueried closest peers remain (was terminating early).
- BETA=3 resiliency: at least 3 closest peers queried before termination.
- Total query timeout (10s per peer) prevents hangs on unresponsive peers.
- Failed peers removed from the routing table.
- Candidates re-sorted by distance after discovering closer peers.

**Security**
- IP diversity filtering: max 2 peers per globally-routable subnet per bucket (eclipse-attack protection, issue #1383).
- Max varint protection: all varint reads use `read_varint_prefixed_bytes_limited` (10-byte prefix cap).
- KAD handlers only registered in server mode.
- Inbound concurrency limiter (max 12 concurrent handlers).

**Bug fixes**
- ADD_PROVIDER sender is fire-and-forget: Kubo never sends an echo response, so waiting for one blocked every announcement for the query timeout (this was the root cause of `dht/provide` timing out against the public network). The receiver still echoes per spec.
- Sliding-window ADD_PROVIDER sends (semaphore, ALPHA in flight) so a slow peer no longer stalls the whole batch.
- Default namespace validators (`pk`, `ipns`) now registered via `apply_fallbacks()` in `KadDHT.__init__` — IPNS records were previously accepted without validation.
- IPNS validator accepts base58btc peer-ID names (`/ipns/<base58>`, the go-ipfs / py-ipfs-lite format) in addition to hex multihash.
- DHT walk self-exclusion: local peer excluded from `peers_to_query` to prevent hangs.
- Correct CID key encoding in `provide`/`find_providers` (`cid_to_bytes(parse_cid())` instead of `key.encode()`).
- PUT_VALUE key comparison fixed (`message.key` vs `record.key`).
- `cleanup_expired` no longer raises `UnboundLocalError` on an empty provider store.
- `get_value` uses network lookup instead of local routing table only.
- Cancel-on-quorum for value retrieval with per-query cancel scopes.
- `BUCKET_SIZE` constant replaces hardcoded 20.
- PUT_VALUE rejects (resets stream) when `validator.select()` fails.
- Routing-table refresh uses a random key within the bucket's XOR range.

**Cleanup**
- Removed dead code: `_propagate_to_closest_peers()`, `is_cid_like_key`, `is_reserved_or_private_addr`, `PEER_REFRESH_INTERVAL`, `_rt_refresh_nursery`, `should_republish()`, `PROVIDER_ADDRESS_TTL`, `gen_random_peer_id_with_cpl()`, `get_active_cpls()`, `_get_providers_from_peer()` wrapper.
- Deduplicated response building (`_add_closer_peers_to_response()`) and key encoding (`_encode_key()`).

### Bitswap (`libp2p/bitswap/`) — closes #1450

- New `BitswapMessageQueue` (Kubo/go-bitswap architecture): one persistent outbound stream per peer, debounced batching of wantlists/cancels/presences/blocks (10–20 ms), automatic stream reconnection without per-message dialing.
- `client.py` rewritten to reuse persistent streams instead of dialing per message.
- No more outbound dial-back streams for `DontHave` responses.
- Fixed O(n) memory growth in `leaf_triples`: peak memory reduced from ~16 GB to ~100 MB on a 2 GB file transfer.
- Removed dead DecisionEngine code; wantlist traces demoted from WARNING to DEBUG.

### Network & Swarm (`libp2p/network/`) — closes #1451

- Dial pipeline aligned with go-libp2p: dial batching, `MaxConcurrentDials=16`, transport ranking.
- Atomic inbound connection cap via `CapacityLimiter.acquire_nowait()`.
- Connection registration shielded from the dial deadline (fixes peers decaying to 0).
- Auto-connector: midpoint target in `[low_water, high_water]`, paced dials (no CPU bursts at 300+ peers), skips relay/IPv6/QUIC-first candidates and private-only peers on public nodes, prevents concurrent auto-connect tasks and dial storms.
- AutoConnector tracking caches pruned; peerstore limit enforced on `add_addrs`.
- `net_stream.is_closed` property added; `INetwork.remove_notifee()` and O(1) `IPeerStore.has_peer()` added.
- Inbound security-upgrade failures logged at DEBUG instead of ERROR.

### QUIC Transport (`libp2p/transport/quic/`) — closes #1452

- Eliminated ServerQuicConnection and registry connection leaks; CIDs purged on disconnect.
- UDP sockets and background tasks guaranteed closed on dial failure/cancellation and in `close()` (FD-leak fixes).
- Event-processing loop de-busy-spun: activity-event signaling, timer-aware polling (1–10 ms), idle sleep, no 2 s delay on expired timers.
- `get_all_cids_for_connection` made O(1).
- Removed temporary stack logging; DEBUG level no longer forced at import.

### Connection Manager (`libp2p/rcmgr/`)

- 15 connection-manager bugs fixed: `max_connections` enforced on outbound dials and at registration (race-free), `min_connections` functional, lifecycle manager wired into the swarm, `add_conn` dedup no longer closes the shared muxed connection, safe per-peer trimming, background pruning with debounce, auto-connect on disconnect with re-dial back-off, notifee failure isolation, deterministic `Swarm.close()`, defensive getter copies, pruner allow-list uses the real remote IP, `dial_peer` results capped, dead connection pool removed.
- Lifecycle-tracker ratchet fixed (node no longer wedges at 0 peers).
- O(1) `has_peer` and raw-byte ID hashing.

### Random Walk / Discovery (`libp2p/discovery/random_walk/`)

- Startup query storms reduced: concurrency 10 → 3, refresh interval 60 s → 120 s.
- Post-walk connection pruning; redundant trim in `RTRefreshManager` removed.

### Yamux (`libp2p/stream_muxer/yamux/`)

- `read()` returns available data without waiting for EOF (prevents reader/writer deadlocks).
- Stale-stream sweeper reclaims bookkeeping for fully-closed streams with unread data.
- Backlog semaphore slot guarded against double-release.

### PubSub (`libp2p/pubsub/`)

- Peer registration retried with capped exponential backoff (0.5–10 s) so peers are never silently left unregistered when the notifee fires before the handshake completes.
- Dead peer streams re-established; new public idempotent `ensure_peer_stream()` API for out-of-band connections.

### Peer & Peerstore (`libp2p/peer/`)

- Memory leaks from `defaultdict` auto-creation plugged; `peer_data_map` now size-limited (default 1000 peers) with eviction.
- `KeyError` fixed in `add_pubkey`/`add_privkey`/metrics on uninitialized peer data.
- `ID.__hash__` hashes raw bytes instead of base58-encoding on every call (dominant CPU cost on production nodes).

### Host / Identify / Ping (`libp2p/host/`)

- `fail_after` replaced with `move_on_after` in `basic_host.py` and multiselect to eliminate `TooSlowError` CPU burn.
- Identify: 60 s backoff on `new_stream` failure, per-peer backoff to prevent cancellation storms, `UnboundLocalError` crash fixed.
- Ping streams closed after completion / reset on error (stream-leak fix).
- Cancellation leak fixed in `new_stream`/`send_command`.

### TLS (`libp2p/security/tls/`)

- Loads the exact `libssl` linked by CPython on macOS so certificate verification works.
- pyrefly type-narrowing errors resolved (unblocked CI).

### Records / IPNS (`libp2p/records/ipns.py`)

- IPNS validator accepts base58btc peer-ID names in `/ipns/` keys in addition to hex multihash.
- With default validators now registered (see DHT fixes), IPNS records are actually validated instead of silently accepted.

### Utils / AnyIO Service

- IPv6 availability probe (cached), relay-address detection for the auto-connector, routability helper with CGNAT allowance.
- `FunctionTask.cancel()` applied to tasks not yet inside their cancel scope (fixes `wait_done()` hanging forever).

## Testing

- 236 DHT + records tests pass; full suite green except 3 pre-existing WebRTC varint-logging failures that also fail on upstream main (unrelated to this PR).
- `make lint` fully green (ruff, mypy, pyrefly).
- Manual staging verification against the public network: `dht/provide` (previously timing out at 30 s), `name/publish`/`name/resolve` (previously failing validation), `cat` of remote content, and `swarm/disconnect` all verified working end-to-end.

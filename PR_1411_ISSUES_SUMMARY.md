# PR #1411 - Issues Summary & Fix Status

**PR:** [#1411 - Audit and comprehensive stability improvements](https://github.com/libp2p/py-libp2p/pull/1411)
**Related Issue:** [#1390 - Shared QuicLogger crash](https://github.com/libp2p/py-libp2p/issues/1390)
**Generated:** 2026-08-02

---

## 1. Kademlia DHT & Random Walk

**8 issues identified and fixed in PR #1411. All 8 are verified fixed in current codebase.**

### 1.1 Random Walk Stalls: Artificial Routing Table Threshold
- **Issue:** `min_refresh_threshold = 4` prevented the DHT from continuously discovering peers, causing it to endlessly redial the same peers.
- **Fix:** Replaced threshold-based approach with time-based `refresh_interval` (default 60s).
- **File:** `libp2p/discovery/random_walk/rt_refresh_manager.py:51-52,131-136`, `libp2p/discovery/random_walk/config.py:6`
- **Status:** FIXED

### 1.2 KBucket Splitting Logic Incorrect
- **Issue:** KBucket splitting did not correctly redistribute peers based on XOR distance.
- **Fix:** Split at midpoint, redistribute peers based on hashed key position, repeatedly split if all peers fall into one half.
- **File:** `libp2p/kad_dht/routing_table.py:321-344,445-457,629-645`
- **Status:** FIXED

### 1.3 KBucket Eviction Logic Incorrect
- **Issue:** Eviction logic pinging the wrong peer (new peer instead of oldest).
- **Fix:** Pings the oldest (least-recently-seen) peer using libp2p ping protocol. Replaces only if unresponsive.
- **File:** `libp2p/kad_dht/routing_table.py:97-145,236-266`
- **Status:** FIXED

### 1.4 Target Keys Not Hashed Before XOR Distance
- **Issue:** Raw target keys used for XOR distance computation instead of hashed keys.
- **Fix:** SHA-256 hash applied to target keys before computing XOR distance.
- **File:** `libp2p/kad_dht/utils.py:188-194`, `libp2p/kad_dht/routing_table.py:37-45,521-527`
- **Status:** FIXED

### 1.5 Random Walk Concurrency Mismatch with go-libp2p
- **Issue:** Random walk concurrency did not match go-libp2p's default of 10.
- **Fix:** `ALPHA = 10` (DHT query concurrency) and `RANDOM_WALK_CONCURRENCY = 10` aligned.
- **File:** `libp2p/kad_dht/common.py:10`, `libp2p/discovery/random_walk/config.py:17`
- **Status:** FIXED

### 1.6 Random Walk Targets Not Configurable
- **Issue:** Random walk targets were hardcoded.
- **Fix:** `RTRefreshManager` accepts `query_function` parameter for configurable peer discovery.
- **File:** `libp2p/discovery/random_walk/rt_refresh_manager.py:44-51`, `libp2p/kad_dht/kad_dht.py:271-287,236-242`
- **Status:** FIXED

### 1.7 Newly Discovered Peers Not Added to Routing Table
- **Issue:** Peers discovered via FIND_NODE responses were not added to the routing table.
- **Fix:** Discovered peers explicitly added to routing table in peer_routing.py and rt_refresh_manager.py.
- **File:** `libp2p/kad_dht/peer_routing.py:301-308,393-415,444-452`, `libp2p/discovery/random_walk/rt_refresh_manager.py:182-187`
- **Status:** FIXED

### 1.8 DNS Address (dnsaddr) Resolution Not Supported
- **Issue:** Kademlia logic did not support `dnsaddr` resolution.
- **Fix:** Bootstrap, connection gate, DNS utils, and TCP transport all support `dnsaddr` resolution.
- **File:** `libp2p/discovery/bootstrap/bootstrap.py:150-153`, `libp2p/network/connection_gate.py:62-66`, `libp2p/utils/dns_utils.py:48-141`, `libp2p/transport/tcp/tcp.py:223-230`
- **Status:** FIXED

---

## 2. Ping Protocol

**10 issues identified in PR #1411. 9 verified fixed, 1 has a remaining concern.**

### 2.1 Stream Leaks & Inbound Limits (Critical)
- **Issue:** Malicious or buggy peers could open unbounded inbound streams, causing coroutine/memory growth.
- **Fix:** Per-peer inbound stream limits (max 2) with rejection via `stream.reset()`.
- **File:** `libp2p/host/ping.py:154,166-169,201-202`
- **Status:** FIXED

### 2.2 Outbound Stream Churn
- **Issue:** Each `ping()` call created a new outbound stream, causing massive stream churn.
- **Fix:** Single outbound stream cached per peer and reused across multiple `ping()` calls.
- **File:** `libp2p/host/ping.py:153,213-217,231-232,236-237`
- **Status:** FIXED

### 2.3 Excessive Response Timeout
- **Issue:** `RESP_TIMEOUT` was 60s, far exceeding go-libp2p's 10s default.
- **Fix:** Reduced to 10 seconds.
- **File:** `libp2p/host/ping.py:32`
- **Status:** FIXED

### 2.4 No Write Timeouts
- **Issue:** `stream.write()` had no timeout, could block indefinitely.
- **Fix:** Write operations wrapped in `trio.fail_after(RESP_TIMEOUT)`.
- **File:** `libp2p/host/ping.py:89-94,116-117`
- **Status:** FIXED

### 2.5 No Cancellation Support
- **Issue:** No way to abort stuck pings.
- **Fix:** `CancelScope` parameter added to `_ping()` and `ping_iter()`.
- **File:** `libp2p/host/ping.py:102,115,208,224`
- **Status:** FIXED

### 2.6 API Semantics Mismatch with go-libp2p
- **Issue:** API did not yield individual RTT values like go-libp2p.
- **Fix:** `ping_iter()` is an async generator yielding `AsyncIterator[int]`.
- **File:** `libp2p/host/ping.py:1,204-226,245-252`
- **Status:** FIXED

### 2.7 RTT Calculations Wrong (Microseconds vs Milliseconds)
- **Issue:** RTT was computed in wrong units.
- **Fix:** Uses `time.monotonic()` and multiplies by 1000 for milliseconds.
- **File:** `libp2p/host/ping.py:113,130`
- **Status:** FIXED

### 2.8 Short-Read Vulnerability
- **Issue:** `stream.read(n)` returns partial data, causing truncated ping payloads.
- **Fix:** `read_exactly()` used to block until full PING_LENGTH is received.
- **File:** `libp2p/host/ping.py:63,124`
- **Status:** FIXED

### 2.9 Wrong Stream Closure on Payload Mismatch
- **Issue:** `close()` used instead of `reset()` on payload mismatches, not signaling error.
- **Fix:** `stream.reset()` used on payload mismatch.
- **File:** `libp2p/host/ping.py:132-138`
- **Status:** FIXED

### 2.10 Metrics Exception Handling (Remaining Concern)
- **Issue:** Unhandled exception in ping metrics would crash the global metrics loop (including gossipsub, kad_dht, swarm).
- **Fix:** PR claims fix but the global metrics loop in `libp2p/metrics/metrics.py:65-76` still lacks a `try/except` wrapper around `.record()` calls. A single malformed event could crash the entire metrics collection task.
- **File:** `libp2p/metrics/metrics.py:65-76`
- **Status:** POTENTIALLY NOT FIXED - The global metrics receive loop has no `try/except` around the `match` statement. If `self.ping.record(event)` raises, the loop crashes.

---

## 3. Identify & IdentifyPush

**21 issues identified in PR #1411. All 21 are verified fixed in current codebase.**

### 3.1 Unbounded Varint Prefix Reads (Critical)
- **Issue:** Stalled peer could hold streams open forever reading unbounded varint data.
- **Fix:** Varint loop bounded to `range(10)`, `max_length` parameter (default 1 MiB), `trio.fail_after(10.0)` timeouts.
- **File:** `libp2p/utils/varint.py:198-216`, `libp2p/identity/identify_push/identify_push.py:76`, `libp2p/host/basic_host.py:1134`
- **Status:** FIXED

### 3.2 Identify Tasks Not Scoped Correctly
- **Issue:** Identify tasks were not cleaned up on connection drop, causing resource leaks.
- **Fix:** Each task runs in `trio.CancelScope` tracked in `_identify_tasks`. All cancelled on `close()`.
- **File:** `libp2p/host/basic_host.py:318-321,1045-1078`
- **Status:** FIXED

### 3.3 Signed Peer Record Mismatch
- **Issue:** Mismatched signed peer record would skip processing of valid observed addresses.
- **Fix:** Cross-checks `record.peer_id != peer_id` and rejects forged records with warning log.
- **File:** `libp2p/identity/update.py:162-187`
- **Status:** FIXED

### 3.4 Unbounded Global Cache Memory Leak
- **Issue:** `_UNPARSEABLE_ADDRS_CACHE` dict grew without bounds.
- **Fix:** Replaced with `functools.lru_cache(maxsize=1000)`.
- **File:** `libp2p/identity/update.py:22-28`
- **Status:** FIXED

### 3.5 `id(conn)` Stale Observation Prevention
- **Issue:** Using `id(conn)` as dict key caused stale observations on reused memory addresses.
- **Fix:** Stores `weakref.ReferenceType[INetConn]` and checks `wref() is not conn` before reuse.
- **File:** `libp2p/host/observed_addr_manager.py:153-157,238-246`
- **Status:** FIXED

### 3.6 Shared Global Semaphore Mutable Default
- **Issue:** `trio.Semaphore` mutable default argument caused cross-call limiting issues.
- **Fix:** Lazy initialization via `_get_push_capacity()` using `None` default with `global` assignment.
- **File:** `libp2p/identity/identify_push/identify_push.py:44-53`
- **Status:** FIXED

### 3.7 5s Synchronous Poll Delay
- **Issue:** 5s blocking poll compounded stream exhaustion under load.
- **Fix:** Async polling with `trio.sleep(0.01)` and tight 0.5s deadline.
- **File:** `libp2p/identity/identify/identify.py:170-172`
- **Status:** FIXED

### 3.8 O(n^2) Bytes Concatenation (DoS Vector)
- **Issue:** Repeated `bytes` concatenation in `read_length_prefixed_protobuf` was O(n^2).
- **Fix:** Uses `bytearray()` with `.extend()` for O(n) concatenation.
- **File:** `libp2p/utils/varint.py:219-230`
- **Status:** FIXED

### 3.9 Protocols Append Instead of Replace
- **Issue:** Protocols accumulated across identify messages instead of being replaced.
- **Fix:** `clear_protocol_data(peer_id)` called before `add_protocols()`.
- **File:** `libp2p/identity/update.py:150-160`
- **Status:** FIXED

### 3.10 Addresses Accumulating Across Pushes
- **Issue:** Listen addresses were never cleared, accumulating across pushes.
- **Fix:** `peerstore.clear_addrs(peer_id)` called before adding new addresses.
- **File:** `libp2p/identity/update.py:116-148`
- **Status:** FIXED

### 3.11 `_is_public_addr` False-Positives
- **Issue:** IPv4-mapped IPv6 addresses (`::ffff:*`) incorrectly classified.
- **Fix:** Comprehensive checks for private/loopback/link-local/multicast/ULA addresses.
- **File:** `libp2p/identity/update.py:31-80`
- **Status:** FIXED

### 3.12 Identify Handler Never Closing Response Stream
- **Issue:** Response stream left open after handling.
- **Fix:** `stream.close()` in `finally` block wrapped in try/except.
- **File:** `libp2p/identity/identify/identify.py:208-212`, `libp2p/identity/identify_push/identify_push.py:103-108`
- **Status:** FIXED

### 3.13 Missing `public_key` Validation
- **Issue:** No validation of `public_key` field in identify response.
- **Fix:** `HasField("public_key")` check in both varint and raw format paths.
- **File:** `libp2p/identity/identify/identify.py:123-124,134-135`
- **Status:** FIXED

### 3.14 Case-Sensitive `::ffff:` Check
- **Issue:** Case-sensitive string comparison for IPv4-mapped addresses.
- **Fix:** Uses `.lower()` before checking prefix.
- **File:** `libp2p/identity/identify/identify.py:67-69`
- **Status:** FIXED

### 3.15 Per-Call Semaphore (No Cross-Call Limiting)
- **Issue:** Semaphore was per-call instead of shared across calls.
- **Fix:** Shared `CapacityLimiter` passed through call chain.
- **File:** `libp2p/identity/identify_push/identify_push.py:113-138,174-209`
- **Status:** FIXED

### 3.16 System Tasks Not Cancelled on Host Shutdown
- **Issue:** Identify tasks leaked on host shutdown.
- **Fix:** `close()` cancels all tracked `_identify_tasks` scopes.
- **File:** `libp2p/host/basic_host.py:1045-1049`
- **Status:** FIXED

### 3.17 No Fallback to Raw Protobuf Format
- **Issue:** `_identify_peer` failed when remote used legacy raw protobuf format.
- **Fix:** Tries varint-prefixed first, falls back to `stream.read()` on failure.
- **File:** `libp2p/host/basic_host.py:1133-1141`
- **Status:** FIXED

### 3.18 `_identify_inflight` Check-Then-Add Race
- **Issue:** Race condition allowed duplicate identify tasks.
- **Fix:** `_identify_inflight.add()` before checks; `discard` in `finally`.
- **File:** `libp2p/host/basic_host.py:1051-1084`
- **Status:** FIXED

### 3.19 `_identified_peers` Stale Write After Disconnect
- **Issue:** Peers marked as identified even after disconnect.
- **Fix:** Checks `get_connections(peer_id)` before writing; entry removed on disconnect.
- **File:** `libp2p/host/basic_host.py:1145-1148,1227-1232`
- **Status:** FIXED

### 3.20 `_has_cached_protocols` Exception Swallowing
- **Issue:** All exceptions silently swallowed.
- **Fix:** `PeerStoreError` caught separately; other `Exception` logged with `exc_info=True`.
- **File:** `libp2p/host/basic_host.py:1086-1107`
- **Status:** FIXED

### 3.21 Missing IPv6 ULA and IPv4 Multicast Checks
- **Issue:** `_is_public_addr` did not filter IPv6 ULA or IPv4 multicast.
- **Fix:** Checks for `fc`/`fd` prefixes (ULA) and 224-239 first octet (multicast).
- **File:** `libp2p/identity/update.py:67-79`
- **Status:** FIXED

---

## 4. Bitswap

**8 issues identified in PR #1411. All 8 are verified fixed in current codebase.**

### 4.1 No Session-Based Architecture
- **Issue:** Bitswap lacked session-based isolation for retrieval states and concurrent fetching.
- **Fix:** Complete rewrite with `BitswapSession`, `BitswapPeerManager`, `BlockPresenceManager`, and `SessionInterestManager`.
- **File:** `libp2p/bitswap/session.py`, `libp2p/bitswap/peer_manager.py`, `libp2p/bitswap/presence.py`, `libp2p/bitswap/sim.py`
- **Status:** FIXED

### 4.2 No Cancel Propagation
- **Issue:** Blocks were not cancelled on peers after receipt, wasting bandwidth.
- **Fix:** `cancel_want()` sends `WANT_CANCEL` to all connected peers. Called in `finally` blocks of session requests.
- **File:** `libp2p/bitswap/client.py:298-315,431-454,1076-1077,1143-1144`, `libp2p/bitswap/session.py:224-234,409-421`
- **Status:** FIXED

### 4.3 Memory Leaks in Internal Data Structures
- **Issue:** Unbounded growth in `_pending_requests`, `_dont_have_responses`, `_expected_blocks`, `_have_confirmed`.
- **Fix:** TTL-based cleanup in `BlockPresenceManager.cleanup_expired()` (every 10s), proper discard/delete in session `finally` blocks, state cleared on `stop()`.
- **File:** `libp2p/bitswap/session.py:224-230,410-421`, `libp2p/bitswap/presence.py:62-78`, `libp2p/bitswap/client.py:137-165,567-585,1063`
- **Status:** FIXED

### 4.4 Race Conditions in `_pending_requests`
- **Issue:** Concurrent fetches of the same CID caused race conditions.
- **Fix:** Uses `set[trio.Event]` per CID for multiple concurrent waiters. Proper add/discard discipline. `receive_block()` iterates over copy of events set.
- **File:** `libp2p/bitswap/session.py:100-103,195-207,432-438,224-230`
- **Status:** FIXED

### 4.5 No Task Management on Shutdown
- **Issue:** Bitswap client loop tasks lingered after shutdown.
- **Fix:** `trio.CancelScope` for background cleanup loop, explicitly cancelled on `stop()`.
- **File:** `libp2p/bitswap/client.py:110,131-134,137-144,146-153`
- **Status:** FIXED

### 4.6 No CID Validation or Block Size Limits
- **Issue:** No structural validation of CIDs or block size enforcement.
- **Fix:** `MAX_BLOCK_SIZE = 512KB`, `MAX_MESSAGE_SIZE = 4MB`, `verify_cid()` recomputes CID from data, `parse_cid()` validates structure.
- **File:** `libp2p/bitswap/config.py:24,27-29`, `libp2p/bitswap/client.py:188-198,1206-1209,1254-1257`, `libp2p/bitswap/cid.py:173-246`
- **Status:** FIXED

### 4.7 `have_block` Correctness
- **Issue:** `have_block()` implementation was incorrect.
- **Fix:** Proper WANT_HAVE with `want_type=1`, `send_dont_have=True`, timeout-based waiting, and cleanup via `cancel_want()`.
- **File:** `libp2p/bitswap/client.py:241-296`
- **Status:** FIXED

### 4.8 Network Error Handling When Sending Responses
- **Issue:** Errors during response sending could crash the client.
- **Fix:** Full try/except/finally around all stream operations. Graceful handling of nursery-closed errors during shutdown.
- **File:** `libp2p/bitswap/client.py:431-454,456-505,560-590,846-876,878-912`
- **Status:** FIXED

---

## 5. QUIC & Transports (Related to Issue #1390)

### 5.1 Shared QuicLogger Crash (Issue #1390)
- **Issue:** Single shared `QuicLogger` instance across concurrent QUIC connections caused `QuicLoggerTrace does not belong to QuicLogger` crash.
- **Fix:** `config.quic_logger = QuicLogger()` removed entirely. `quic_logger` stays at default `None`, disabling trace creation.
- **File:** `libp2p/transport/quic/transport.py:281-282`
- **Status:** FIXED

---

## Overall Summary

| Module | Issues Found | Fixed | Remaining Concerns |
|--------|-------------|-------|-------------------|
| Kademlia DHT | 8 | 8 | 0 |
| Ping | 10 | 9 | 1 (metrics exception handling) |
| Identify | 21 | 21 | 0 |
| Bitswap | 8 | 8 | 0 |
| QUIC (#1390) | 1 | 1 | 0 |
| **Total** | **48** | **47** | **1** |

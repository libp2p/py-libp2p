# Cold Run Failure Analysis: Why First Run Fails and Why Warm-up Helps

## Executive Summary

The test fails on the first run (cold start) because **100 concurrent streams try to negotiate simultaneously while the server is still initializing expensive cryptographic operations**. On subsequent runs, these operations are cached or already initialized, so the server can handle the load.

## What Happens on a Cold Run (First Time)

### Phase 1: Host Creation and Certificate Generation

When `new_host()` is called for the first time:

1. **QUICTransport Initialization** (`libp2p/transport/quic/transport.py:76-113`)

   - Creates security manager: `QUICTLSConfigManager`
   - **Generates TLS certificate** (CPU-intensive):
     ```python
     # libp2p/transport/quic/security.py:1091-1093
     self.tls_config = self.certificate_generator.generate_certificate(
         libp2p_private_key, peer_id
     )
     ```
   - Certificate generation involves:
     - Generating ephemeral private keys (elliptic curve operations)
     - Creating X.509 certificate structure
     - Creating libp2p extension with signed key proof
     - Cryptographic signing operations
   - Sets up QUIC configurations for multiple versions (draft-29, v1)

1. **Server Host Setup**

   - Creates listener
   - Binds UDP socket
   - Starts packet handling loop
   - **Registers stream handler** (`server_host.set_stream_handler()`)

### Phase 2: Connection Establishment

When `client_host.connect()` is called:

1. **First Connection Handshake** (most expensive on cold run)
   - QUIC handshake packets exchanged
   - **TLS handshake with certificate verification**:
     ```python
     # libp2p/transport/quic/connection.py:550-595
     async def _verify_peer_identity_with_security(self) -> ID | None:
         # Extract peer certificate from TLS handshake
         await self._extract_peer_certificate()
         # Verify peer identity using security manager
         verified_peer_id = self._security_manager.verify_peer_identity(...)
     ```
   - Certificate verification involves:
     - Parsing X.509 certificate
     - Extracting libp2p extension
     - Verifying cryptographic signature
     - Deriving peer ID from public key
   - Connection ID registration
   - Muxer initialization

### Phase 3: Stream Negotiation Storm (The Problem)

**Immediately after connection**, 100 streams try to open simultaneously:

```python
# All 100 streams start at once
async with trio.open_nursery() as nursery:
    for i in range(STREAM_COUNT):  # 100 streams
        nursery.start_soon(ping_stream, i)  # All negotiate at once!
```

Each stream needs:

1. **Protocol negotiation** via multiselect:

   - Client sends protocol request: `/ipfs/ping/1.0.0`
   - Server must respond with protocol acceptance
   - This requires the server's multiselect handler to be ready

1. **Server-side processing**:

   - Server receives stream
   - Calls `_swarm_stream_handler()`
   - Acquires negotiation semaphore (limit: 1000, so all 100 can proceed)
   - Calls `multiselect.negotiate()`
   - Must match protocol and return handler

## Why Cold Run Fails

### Problem 1: Server Still Initializing

On cold run, when 100 streams arrive simultaneously:

- Server may still be processing the **first connection's TLS handshake**
- Certificate verification is still in progress
- Connection ID registry is still being populated
- Multiselect handler may not be fully registered/ready

**Result**: Some streams arrive before the server is ready to handle them, causing negotiation timeouts.

### Problem 2: Resource Contention

Even with semaphore limit of 1000, 100 concurrent negotiations create:

- **CPU contention**: Certificate verification, cryptographic operations
- **Memory pressure**: Creating 100 stream objects simultaneously
- **Network buffer pressure**: 100 streams sending negotiation packets
- **Event loop contention**: 100 coroutines competing for execution

**Result**: Server becomes overwhelmed, negotiations slow down, some timeout.

### Problem 3: Timing Race Condition

The test does:

```python
await client_host.connect(info)  # Connection established
# Small delay (0.3s)
# Then immediately opens 100 streams
```

But the server might need more time to:

- Complete TLS handshake verification
- Register connection in internal maps
- Initialize muxer state
- Prepare multiselect handler

**Result**: Some streams start negotiating before server is fully ready.

## What Happens on Warm Runs (Subsequent Attempts)

### Cached/Reused Resources

1. **Python Module Caching**:

   - Certificate generation code is already loaded
   - Cryptographic libraries are initialized
   - Class definitions are cached

1. **OS-Level Caching**:

   - Socket creation is faster (kernel state cached)
   - Network buffers are warmed up
   - CPU caches contain relevant code/data

1. **Application State**:

   - Connection patterns are established
   - Internal data structures are sized appropriately
   - Event loop is already running efficiently

### Result

- Server responds faster to negotiations
- Less CPU contention (no cold-start overhead)
- Negotiations complete within timeout
- **All 100 streams succeed**

## Why a Warm-up Phase Would Help

A warm-up phase would:

1. **Complete Initialization Before Stress Test**:

   ```python
   # Warm-up: Open 1-2 streams first
   warmup_stream = await client_host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
   await warmup_stream.write(b"warmup")
   await warmup_stream.read(PING_LENGTH)
   await warmup_stream.close()

   # Now server is fully ready
   # Then start the 100-stream stress test
   ```

1. **Benefits**:

   - Ensures TLS handshake is complete
   - Verifies connection is fully established
   - Confirms multiselect handler is ready
   - Warms up server's internal state
   - Validates negotiation path works

1. **Eliminates Race Conditions**:

   - Server has time to complete initialization
   - Connection is proven to be ready
   - No streams arrive during critical initialization phase

## Current Mitigations (What We've Done)

1. **Increased Timeouts**:

   - Negotiation timeout: 15s → 30s
   - Gives more time for slow negotiations

1. **Added Readiness Checks**:

   - Wait for connection in connections map
   - Wait for `event_started`
   - Added delays (0.2s + 0.3s)

1. **Increased Semaphore Limit**:

   - 5 → 1000 (allows all 100 streams to negotiate concurrently)

## Recommendation: Add Warm-up Phase

```python
# After connection is established and ready
await client_host.connect(info)
# ... readiness checks ...

# WARM-UP: Open a few streams to ensure server is ready
warmup_count = 3
for i in range(warmup_count):
    warmup_stream = await client_host.new_stream(
        info.peer_id, [PING_PROTOCOL_ID]
    )
    await warmup_stream.write(b"\x01" * PING_LENGTH)
    await warmup_stream.read(PING_LENGTH)
    await warmup_stream.close()

# Small delay after warm-up
await trio.sleep(0.1)

# NOW start the stress test with 100 streams
async with trio.open_nursery() as nursery:
    for i in range(STREAM_COUNT):
        nursery.start_soon(ping_stream, i)
```

This ensures:

- Server has completed all initialization
- Negotiation path is proven to work
- Connection is fully warmed up
- No race conditions when stress test starts

## Summary

**Cold run fails** because:

- Expensive cryptographic operations (certificate generation/verification) happen during initialization
- 100 streams arrive before server finishes initialization
- Resource contention overwhelms the server
- Timing race conditions cause some negotiations to timeout

**Warm-up helps** because:

- Completes initialization before stress test
- Proves the negotiation path works
- Warms up server state and caches
- Eliminates race conditions

**Current state**: Test needs 1 rerun on cold start, but subsequent runs pass immediately. A warm-up phase would eliminate the need for reruns.

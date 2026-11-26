# QUIC vs TCP: Why QUIC Re-runs Multiselect for Every Stream

## Executive Summary

**The fundamental difference**: TCP uses a two-layer architecture where multiselect negotiation happens ONCE per connection to establish a stream multiplexer (Yamux), while QUIC treats each stream as an independent entity requiring its own protocol negotiation.

## Detailed Architecture Comparison

### TCP + Yamux Architecture (Two-Layer)

```
1. TCP Connection Established
   ↓
2. Security Layer (Noise/Secio) - ONE negotiation
   ↓
3. Muxer Layer (Yamux) - ONE multiselect negotiation
   ↓
4. Yamux Connection Established
   ↓
5. Stream 1: Just send Yamux stream ID (no negotiation)
   Stream 2: Just send Yamux stream ID (no negotiation)
   Stream 3: Just send Yamux stream ID (no negotiation)
   ...
```

**Key Point**: After the initial Yamux negotiation, all subsequent streams are just Yamux stream IDs. No protocol negotiation needed per stream.

**Code Flow**:

1. `TransportUpgrader.upgrade_connection()` → negotiates Yamux ONCE
1. `Yamux.open_stream()` → just creates a stream ID, no negotiation
1. `BasicHost.new_stream()` → gets a Yamux stream, then negotiates APPLICATION protocol

Wait, that's not quite right. Let me check...

Actually, looking at the code:

- TCP: `new_stream()` → creates Yamux stream → negotiates application protocol via multiselect
- QUIC: `new_stream()` → creates QUIC stream → negotiates application protocol via multiselect

So BOTH negotiate the application protocol per stream! But the difference is...

### QUIC Architecture (Single-Layer)

```
1. QUIC Connection Established (with TLS built-in)
   ↓
2. Stream 1: Create QUIC stream → multiselect negotiation for /ipfs/ping/1.0.0
   Stream 2: Create QUIC stream → multiselect negotiation for /ipfs/ping/1.0.0
   Stream 3: Create QUIC stream → multiselect negotiation for /ipfs/ping/1.0.0
   ...
```

**Key Point**: QUIC doesn't use a separate muxer layer like Yamux. Each QUIC stream is treated as a raw stream that needs protocol negotiation.

## Why the Difference?

### TCP's Two-Layer Design

1. **Transport Layer**: TCP connection
1. **Muxer Layer**: Yamux (negotiated once via multiselect)
1. **Application Layer**: Each Yamux stream negotiates its protocol

The muxer layer (Yamux) is negotiated ONCE when the connection is upgraded. After that, Yamux handles all stream multiplexing internally.

### QUIC's Single-Layer Design

1. **Transport Layer**: QUIC connection (with built-in multiplexing)
1. **Application Layer**: Each QUIC stream negotiates its protocol

QUIC provides native stream multiplexing, so there's no separate muxer layer. Each stream is independent and needs its own protocol negotiation.

## The Real Question: Can We Cache Protocol Negotiation?

Looking at the code in `basic_host.py`:

```python
async def new_stream(self, peer_id: ID, protocol_ids: Sequence[TProtocol]) -> INetStream:
    net_stream = await self._network.new_stream(peer_id)
    # ... multiselect negotiation happens here for EVERY stream
    selected_protocol = await self.multiselect_client.select_one_of(...)
```

**Both TCP and QUIC negotiate the application protocol for every stream!**

So why does TCP perform better? The difference is NOT in the protocol negotiation itself, but in the **underlying stream creation and server-side processing**.

## The Actual Difference: Stream Creation Overhead

### TCP/Yamux Stream Creation

```python
# libp2p/stream_muxer/yamux/yamux.py:open_stream()
async def open_stream(self) -> YamuxStream:
    # Just allocate stream ID and send a header
    stream_id = self.next_stream_id
    self.next_stream_id += 2
    stream = YamuxStream(stream_id, self, True)
    header = struct.pack(YAMUX_HEADER_FORMAT, 0, TYPE_DATA, FLAG_SYN, stream_id, 0)
    await self.secured_conn.write(header)
    return stream
```

- **Very lightweight**: Just allocate an ID and send a small header
- Yamux stream is immediately ready for protocol negotiation
- Minimal overhead

### QUIC Stream Creation

```python
# libp2p/transport/quic/connection.py:open_stream()
async def open_stream(self, timeout: float | None = None) -> QUICStream:
    # Acquire lock, check limits, generate stream ID, create stream object
    async with self._stream_lock:
        stream_id = self._next_stream_id
        self._next_stream_id += 4
        stream = QUICStream(...)
        self._streams[stream_id] = stream
        # ... more state management
    return stream
```

- **More overhead**: Lock acquisition, stream state management, QUIC protocol state
- QUIC stream needs to be registered in connection state
- More complex lifecycle management

## The Real Bottleneck: Server-Side Processing

From the CI logs, we see:

- Stream #40 timed out after 30s
- Error: "response timed out after 30s, protocols tried: ['/ipfs/ping/1.0.0']"

This means the **server** couldn't respond in time. Why?

### Server-Side Flow

**TCP**:

1. Incoming Yamux stream arrives
1. Server calls `_swarm_stream_handler()`
1. Negotiates protocol (lightweight, Yamux stream already established)
1. Handles request

**QUIC**:

1. Incoming QUIC stream arrives
1. Server calls `_swarm_stream_handler()`
1. Negotiates protocol (on QUIC stream, which may have overhead)
1. Handles request

The issue is more nuanced: with 50 concurrent streams, the **client-side semaphore** (limit 5) creates a queue where 45 streams wait. When streams finally get through the client semaphore and try to negotiate with the server, they may have already been waiting a long time. The **server-side semaphore** (also limit 5) protects the server from being overwhelmed, but the cumulative delay from client-side queueing + server processing time can cause some streams to exceed the 30s timeout.

## Can We Make QUIC Behave Like TCP?

### Option 1: Protocol Negotiation Caching

**Idea**: Cache the negotiated protocol per connection, so subsequent streams skip negotiation.

**Problem**: Different streams may need different protocols. We can't assume all streams use the same protocol.

**Partial Solution**: Cache per (connection, protocol_id) pair. But this adds complexity and may not help if protocols vary.

### Option 2: Pre-negotiate Common Protocols

**Idea**: During connection establishment, negotiate common protocols in advance.

**Problem**: We don't know which protocols will be needed. Also, this violates the libp2p design where protocols are negotiated per stream.

### Option 3: Optimize Server-Side Processing

**Current State**: Both client and server use separate semaphores (limit 5 each).

**Code Evidence**:

1. **Default Configuration** (`libp2p/transport/quic/config.py:119`):

```python
NEGOTIATION_SEMAPHORE_LIMIT: int = 5
"""Maximum concurrent multiselect negotiations per direction (client/server)."""
```

2. **Semaphore Initialization** (`libp2p/transport/quic/connection.py:137-146`):

```python
negotiation_limit = getattr(
    self._transport._config, "NEGOTIATION_SEMAPHORE_LIMIT", 5
)
# Ensure it's an int (handles Mock objects in tests)
if not isinstance(negotiation_limit, int):
    negotiation_limit = 5
self._client_negotiation_semaphore = trio.Semaphore(negotiation_limit)
self._server_negotiation_semaphore = trio.Semaphore(negotiation_limit)
# Keep _negotiation_semaphore for backward compatibility (maps to client)
self._negotiation_semaphore = self._client_negotiation_semaphore
```

3. **Client-Side Usage** (`libp2p/host/basic_host.py:341-348`):

```python
if negotiation_semaphore is not None:
    # Use connection-level semaphore to throttle negotiations
    async with negotiation_semaphore:  # Uses _client_negotiation_semaphore
        selected_protocol = await self.multiselect_client.select_one_of(
            list(protocol_ids),
            MultiselectCommunicator(net_stream),
            self.negotiate_timeout,
        )
```

4. **Server-Side Usage** (`libp2p/host/basic_host.py:531-535`):

```python
semaphore_to_use = server_semaphore or negotiation_semaphore
async with semaphore_to_use:  # Uses _server_negotiation_semaphore
    protocol, handler = await self.multiselect.negotiate(
        MultiselectCommunicator(net_stream), self.negotiate_timeout
    )
```

**Result**: With 50 concurrent streams, only 5 can negotiate on client side at once, and only 5 can negotiate on server side at once. The remaining 45 streams wait in the client-side queue.

**Potential Improvements**:

1. Increase semaphore limit (but this may cause resource exhaustion)
1. Optimize multiselect negotiation code (reduce overhead)
1. Use connection-level protocol cache (if same protocol used repeatedly)

### Option 4: Accept the Architectural Difference

**Reality**: QUIC and TCP have different architectures. QUIC's native multiplexing means each stream is independent, which is actually a feature (better isolation, no head-of-line blocking).

The trade-off is that each stream needs protocol negotiation, which adds overhead under high concurrency.

## Why TCP Doesn't Have This Problem

1. **Yamux stream creation is lighter**: Just allocate an ID and send a header (minimal overhead)
1. **QUIC stream creation has more overhead**: Lock acquisition, state management, QUIC protocol state
1. **Server-side processing**: With 50 concurrent QUIC streams, the server's multiselect handler gets overwhelmed even with semaphore protection
1. **Different resource model**:
   - TCP: Heavy connection setup, but lightweight stream creation
   - QUIC: Lighter connection setup (built-in), but more overhead per stream

## The Real Bottleneck: Client-Side Queueing + Server Processing Time

From the CI logs:

- Stream #40 timed out after 30s waiting for server response
- Error: "response timed out after 30s, protocols tried: ['/ipfs/ping/1.0.0']"

**What's actually happening**:

1. Client creates 50 streams simultaneously
1. All 50 try to acquire **client semaphore** (limit 5) - only 5 can proceed
1. 45 streams wait in **client-side queue**
1. The 5 that got through try to negotiate with server
1. Server has its own **server semaphore** (limit 5) - can handle 5 concurrent negotiations
1. **The semaphore protects the server** - it's NOT overwhelmed
1. However, streams waiting in the client queue accumulate wait time
1. When later streams finally get through the client semaphore, they may have already waited 10-20s
1. If server processing is also slow, total time (client wait + server processing) exceeds 30s timeout

**Why TCP doesn't have this issue**:

- Yamux stream creation is faster, so client-side queue drains quicker
- Less overhead means server processes negotiations faster
- Less cumulative delay = fewer timeouts

## Conclusion

**QUIC re-runs multiselect for every stream because**:

1. Both TCP and QUIC negotiate application protocols per stream (this is libp2p's design)
1. QUIC stream creation has more overhead than Yamux stream creation
1. Server-side semaphore (limit 5) creates contention with 50 concurrent streams
1. QUIC's additional overhead + semaphore contention = timeouts

**Can we modify QUIC to behave like TCP?**

- **Not directly**: QUIC streams inherently have more overhead than Yamux streams
- **Possible optimizations**:
  1. **Increase semaphore limit**: Allow more concurrent negotiations (but risk resource exhaustion)
  1. **Optimize QUIC stream creation**: Reduce overhead in `open_stream()`
  1. **Protocol negotiation caching**: Cache per (connection, protocol) pair (complex, may not help)
  1. **Server-side processing optimization**: Make multiselect negotiation faster
  1. **Accept higher timeout**: Current 30s may still be too low for high concurrency

**The real issue**: Server-side bottleneck when handling many concurrent negotiations. The semaphore helps but creates a queue. With QUIC's additional overhead per stream, the queue backs up faster than with TCP/Yamux.

**Recommendation**:

- Accept that QUIC has different performance characteristics than TCP
- Optimize within QUIC's constraints (better semaphore management, faster negotiation code)
- Consider increasing semaphore limit for high-concurrency scenarios (with resource monitoring)

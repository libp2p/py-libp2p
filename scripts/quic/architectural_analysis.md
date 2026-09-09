# Architectural Analysis: QUIC Multiselect Negotiation Timeouts

## Critical Finding: Asymmetric Semaphore Usage

### Client Side (Outbound Streams)

- **Location**: `libp2p/host/basic_host.py:new_stream()`
- **Flow**:
  1. `_network.new_stream(peer_id)` creates stream
  1. Acquires `_negotiation_semaphore` (limit: 5)
  1. Calls `multiselect_client.select_one_of()` within semaphore
  1. Releases semaphore after negotiation

### Server Side (Inbound Streams)

- **Location**: `libp2p/host/basic_host.py:_swarm_stream_handler()`
- **Flow**:
  1. Incoming stream arrives
  1. `_swarm_stream_handler()` called directly
  1. Calls `multiselect.negotiate()`
  1. **NO SEMAPHORE PROTECTION!**

## Problem Analysis

### Issue 1: Server-Side Overload

- **Problem**: Server can handle unlimited concurrent negotiations
- **Impact**: Under load (100 streams), server may be overwhelmed
- **Symptom**: Server responses slow down, causing client timeouts

### Issue 2: Semaphore Timing

- **Problem**: Semaphore acquired AFTER stream creation
- **Impact**: If stream creation is slow, semaphore doesn't help
- **Symptom**: Streams created but negotiation blocked

### Issue 3: No Backpressure Mechanism

- **Problem**: No way to signal server is overloaded
- **Impact**: Client keeps trying, server keeps accepting
- **Symptom**: Cascading timeouts

## Potential Race Conditions

### Race 1: Stream Creation vs Negotiation

```
Client: new_stream() → creates stream → acquires semaphore → negotiates
Server: accepts stream → immediately negotiates (no semaphore)
```

If server is slow, client times out even though stream was created.

### Race 2: Multiple Streams on Same Connection

```
Stream 1: Acquires semaphore slot 1 → negotiating...
Stream 2: Acquires semaphore slot 2 → negotiating...
...
Stream 6: Waits for semaphore → timeout (all 5 slots busy)
```

If any of streams 1-5 are slow, stream 6 times out.

### Race 3: Server Handler Overload

```
100 streams arrive simultaneously
All 100 call multiselect.negotiate() concurrently
Server CPU/IO overwhelmed
All negotiations slow down
Client timeouts occur
```

## Recommended Fixes

### Fix 1: Add Server-Side Semaphore

- Add `_negotiation_semaphore` to server-side negotiation
- Use same limit (5) or make it configurable
- Apply in `_swarm_stream_handler()` before `multiselect.negotiate()`

### Fix 2: Move Semaphore Before Stream Creation

- Acquire semaphore BEFORE creating stream
- This prevents creating streams that can't negotiate
- Reduces resource waste

### Fix 3: Add Connection-Level Backpressure

- Track active negotiations per connection
- Reject new streams if connection is overloaded
- Return error immediately instead of timing out

### Fix 4: Increase Semaphore Limit

- Current limit (5) may be too low for 100 concurrent streams
- Consider increasing to 10-15
- Or make it adaptive based on connection capacity

## Testing Strategy

1. **Test server-side overload**: Send 100 streams simultaneously, measure negotiation times
1. **Test semaphore contention**: Verify streams 6+ wait properly
1. **Test timeout distribution**: Check if timeouts correlate with server load
1. **Test with server-side semaphore**: Verify if adding semaphore fixes timeouts

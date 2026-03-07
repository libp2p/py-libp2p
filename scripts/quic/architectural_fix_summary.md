# Architectural Fix Summary: Server-Side Semaphore Protection

## Problem Identified

**Critical Architectural Flaw**: Asymmetric semaphore usage between client and server

### Before Fix

**Client Side (Outbound Streams)**:

- ✅ Uses `_negotiation_semaphore` (limit: 5)
- ✅ Limits concurrent negotiations
- ✅ Prevents client-side overload

**Server Side (Inbound Streams)**:

- ❌ NO semaphore protection
- ❌ Unlimited concurrent negotiations
- ❌ Server can be overwhelmed under load

### Impact

When 100 streams arrive simultaneously:

1. Client creates 100 streams (throttled by semaphore to 5 concurrent negotiations)
1. Server receives 100 streams and tries to negotiate ALL 100 concurrently
1. Server CPU/IO overwhelmed
1. Negotiations slow down
1. Client timeouts occur (15s timeout exceeded)
1. Test failures (46% failure rate)

## Fix Implemented

### Changes Made

**File**: `libp2p/host/basic_host.py`
**Method**: `_swarm_stream_handler()`

Added server-side semaphore protection matching client-side behavior:

```python
# For QUIC connections, use connection-level semaphore to limit
# concurrent negotiations and prevent server-side overload
muxed_conn = getattr(net_stream, "muxed_conn", None)
negotiation_semaphore = None
if muxed_conn is not None:
    negotiation_semaphore = getattr(
        muxed_conn, "_negotiation_semaphore", None
    )

if negotiation_semaphore is not None:
    # Use connection-level semaphore to throttle server-side negotiations
    async with negotiation_semaphore:
        protocol, handler = await self.multiselect.negotiate(...)
else:
    # For non-QUIC connections, negotiate directly
    protocol, handler = await self.multiselect.negotiate(...)
```

### Benefits

1. **Symmetric Protection**: Both client and server now use the same semaphore
1. **Prevents Server Overload**: Limits concurrent negotiations to 5 (same as client)
1. **Better Resource Management**: Server can't be overwhelmed by too many simultaneous streams
1. **Reduced Timeouts**: Server responds faster, reducing client timeout failures

## Expected Results

- **Reduced failure rate**: From ~46% to significantly lower
- **Better load distribution**: Server handles load more gracefully
- **Symmetric behavior**: Client and server have matching protection
- **More predictable performance**: Negotiations complete within timeout

## Testing

Run 50 iterations to verify improvement:

```bash
python analyze_test_failures_v2.py 50
```

Expected: Failure rate should drop significantly (target: \<10%)

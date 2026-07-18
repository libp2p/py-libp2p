# Timeout Investigation and Fix Plan

## Issues Identified

### 1. Connection Readiness Race Condition

- **Problem**: Test waits for `event_started` but QUICConnection uses `_connected_event` which is set when handshake completes
- **Impact**: Early streams may start before connection is truly ready for negotiation
- **Evidence**: Streams #1-13 fail more frequently

### 2. Negotiation Timeout Under Load

- **Current**: 10 seconds default in BasicHost
- **Problem**: With 5 concurrent negotiations, if one takes longer, others waiting on semaphore may timeout
- **Evidence**: Timeout errors during multiselect negotiation

### 3. Read Timeout After Negotiation

- **Current**: 30 seconds stream read timeout
- **Problem**: If negotiation takes too long, stream might not be ready for reading
- **Evidence**: "Read timeout on stream" errors

### 4. Semaphore Contention

- **Current**: 5 concurrent negotiations
- **Problem**: All 5 slots might be occupied, causing 6th+ stream to wait and potentially timeout
- **Evidence**: Distributed failures across stream indices

## Proposed Fixes

### Fix 1: Improve Connection Readiness Check

- Wait for `_connected_event` or check `is_established` property
- Ensure handshake is truly completed before starting streams
- Add small delay after connection is ready to ensure muxer is initialized

### Fix 2: Increase Negotiation Timeout Under Load

- Increase `DEFAULT_NEGOTIATE_TIMEOUT` from 10 to 15 seconds for QUIC connections
- Or make it adaptive based on connection type and load

### Fix 3: Better Error Handling

- Distinguish between negotiation timeouts and read timeouts
- Add retry logic for transient negotiation failures
- Improve error messages to identify root cause

### Fix 4: Consider Increasing Semaphore Limit

- Test if increasing from 5 to 8 helps (matching test semaphore)
- Monitor if this causes other issues

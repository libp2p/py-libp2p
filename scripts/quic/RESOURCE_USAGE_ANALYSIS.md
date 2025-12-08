# Resource Usage Analysis: Why CPU Spins Up on Test Failure

## Problem

When the test fails and needs a rerun, the CPU fan spins up significantly, indicating excessive resource usage.

## Root Causes

### 1. **100 Concurrent Stream Cleanups**

When the test times out or fails:

- **100 streams** are all in various states (negotiating, reading, writing, failing)
- Each stream tries to clean up simultaneously:
  - Reset the stream
  - Release memory resources
  - Remove from connection registry
  - Close network buffers
- This creates **massive CPU contention** as 100 coroutines compete for:
  - CPU time
  - Memory allocation/deallocation
  - Network I/O operations
  - Lock acquisition

### 2. **No Explicit Cancellation on Timeout**

When `trio.fail_after(120)` times out:

- The exception is raised
- But **all 100 stream tasks continue running** in the nursery
- They're not explicitly cancelled
- They continue trying to complete/cleanup
- This causes:
  - Continued CPU usage
  - Continued memory pressure
  - Continued network I/O
  - Resource leaks if cleanup doesn't complete

### 3. **Insufficient Rerun Delay**

The original `reruns_delay=2` seconds might not be enough:

- Cleanup from 100 streams can take longer than 2 seconds
- When the test reruns, old resources might still be cleaning up
- This causes **resource accumulation**:
  - Old streams still cleaning up
  - New streams starting
  - Double the load = double the CPU usage

### 4. **Connection Not Properly Closed**

If the test fails:

- The connection might still be open
- All 100 streams are still associated with it
- Connection cleanup tries to close all streams
- This creates a **cleanup cascade**:
  - Connection tries to close 100 streams
  - Each stream tries to clean up
  - All happening concurrently
  - Massive CPU usage

### 5. **Exception Handling Overhead**

When 100 streams fail:

- Each one catches an exception
- Each one tries to reset the stream
- Each one logs/prints errors
- This creates:
  - Exception handling overhead
  - Logging overhead
  - I/O overhead (printing to console)
  - All multiplied by 100

## Solutions Implemented

### 1. **Explicit Cancellation on Timeout**

```python
try:
    with trio.fail_after(120):
        await completion_event.wait()
except trio.TooSlowError:
    # Cancel all remaining streams immediately
    nursery.cancel_scope.cancel()
    await trio.sleep(0.5)  # Brief cleanup window
    raise
```

**Benefits**:

- Stops all stream tasks immediately
- Prevents continued resource usage
- Gives brief window for cleanup
- Prevents resource leaks

### 2. **Proper Cancellation Handling in Streams**

```python
except trio.Cancelled:
    # Clean up quickly without excessive logging
    if stream:
        try:
            await stream.reset()
        except Exception:
            pass
    raise  # Re-raise to properly propagate
```

**Benefits**:

- Streams handle cancellation gracefully
- Quick cleanup without logging overhead
- Proper cancellation propagation
- Prevents exception handling overhead

### 3. **Increased Rerun Delay**

Changed from `reruns_delay=2` to `reruns_delay=5`:

**Benefits**:

- More time for cleanup to complete
- Prevents resource accumulation
- Reduces CPU usage on rerun
- Allows system to settle

### 4. **Better Logging on Timeout**

```python
logger.warning(
    f"Test timeout after 120s: {completed_count[0]}/{STREAM_COUNT} streams completed. "
    "Cancelling remaining streams to prevent resource leaks."
)
```

**Benefits**:

- Clear indication of what's happening
- Helps debugging
- Shows progress before timeout

## Expected Impact

### Before Fixes:

- **On timeout**: 100 streams continue running, high CPU usage
- **On rerun**: Old resources still cleaning up + new test starting = 2x load
- **CPU fan**: Spins up significantly
- **Resource leaks**: Possible if cleanup doesn't complete

### After Fixes:

- **On timeout**: All streams cancelled immediately, cleanup window, then stop
- **On rerun**: 5-second delay allows full cleanup before new test
- **CPU fan**: Should spin up less (or not at all)
- **Resource leaks**: Prevented by explicit cancellation

## Additional Recommendations

1. **Monitor Resource Usage**: Add resource monitoring to detect leaks
1. **Gradual Cleanup**: Consider closing streams in batches instead of all at once
1. **Connection Timeout**: Add connection-level timeout to prevent hanging connections
1. **Resource Limits**: Consider limiting concurrent streams to prevent overwhelming system

## Testing

To verify the fixes work:

1. Run the test and intentionally cause a timeout
1. Monitor CPU usage during failure
1. Monitor CPU usage during rerun delay
1. Check for resource leaks (memory, file descriptors, sockets)
1. Verify cleanup completes within rerun delay

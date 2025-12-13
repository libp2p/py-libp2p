# Test Failure Analysis Report: `test_yamux_stress_ping`

## Summary

- **Test**: `tests/core/transport/quic/test_integration.py::test_yamux_stress_ping`
- **Analysis Period**: 50 test runs
- **Failure Rate**: 40% (20/50 runs failed)
- **Total Timeout Errors**: 67 across all failures

## Key Findings

### 1. Error Pattern

- **100% of failures are timeout errors** during multiselect protocol negotiation
- When failures occur, typically 88-98 out of 100 streams succeed (88-98% success rate)
- Failures typically affect 1-10 streams per test run

### 2. Most Frequently Failed Stream Indices

| Stream # | Failures | Notes                                                |
| -------- | -------- | ---------------------------------------------------- |
| #8       | 10       | **Most common failure** - exactly at semaphore limit |
| #5       | 7        | Early stream                                         |
| #10      | 6        | Early stream                                         |
| #12      | 6        | Early stream                                         |
| #9       | 5        | Early stream                                         |
| #13      | 5        | Early stream                                         |
| #91      | 5        | Late stream (clustering pattern)                     |

### 3. Critical Observations

#### Stream #8 Pattern

- Stream #8 fails **10 times** - the most frequent failure
- This is **exactly at the semaphore limit** (test uses `trio.Semaphore(8)`)
- Suggests contention when 8 streams try to negotiate simultaneously

#### Early Stream Failures

- Streams #1-13 fail more frequently than later streams
- Suggests the connection might not be fully ready when early streams start
- The test waits for `event_started` and sleeps 0.05s, but this may not be sufficient

#### Clustering Pattern

- Some failures show clusters (e.g., streams 86-94 in one run)
- Suggests temporary contention or resource exhaustion

### 4. Root Cause Hypothesis

1. **Semaphore Contention**: The test uses `trio.Semaphore(8)` while `QUICConnection` uses `_negotiation_semaphore = trio.Semaphore(5)`. When 8 streams are allowed to proceed, but only 5 can negotiate simultaneously, the 6th-8th streams may timeout waiting.

1. **Connection Readiness Race**: Early streams (especially #1-13) may start before the QUIC connection is fully ready for multiselect negotiation, despite the `event_started` wait.

1. **Timeout Configuration**: The multiselect negotiation timeout may be too short under load, especially when multiple streams are queued.

### 5. Recommendations

#### Immediate Fixes

1. **Match Semaphore Limits**: Reduce test semaphore from 8 to 5 to match `QUICConnection._negotiation_semaphore`
1. **Increase Readiness Wait**: Add a more robust check that the connection is ready for streams (not just `event_started`)
1. **Increase Negotiation Timeout**: Consider increasing the multiselect negotiation timeout under load

#### Investigation Needed

1. **Check if `_negotiation_semaphore` limit of 5 is appropriate** - maybe it should be higher
1. **Verify connection readiness** - ensure `event_started` truly means streams can be opened
1. **Monitor lock contention** - check if registry lock contention is contributing to timeouts

### 6. Next Steps

1. Run test with semaphore reduced to 5 and see if failure rate decreases
1. Add more detailed logging around stream #8 failures
1. Check if increasing `_negotiation_semaphore` from 5 to 8 or 10 helps
1. Investigate if there's a better way to ensure connection readiness

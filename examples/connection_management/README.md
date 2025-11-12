# Connection Management Examples

This directory provides illustrative Python examples showcasing a range of connection management features implemented in libp2p’s `ys-lib`. Each example demonstrates real-world configuration and runtime behaviors for different aspects of connection control, protection, and monitoring.

## Overview of Examples

Below is a summary of the Python example scripts provided here, each focusing on a critical connection management feature:

______________________________________________________________________

### 1. Connection Limits ([connection_limits_example.py](connection_limits_example.py))

**What it Shows:**

- How to set limits on the total number of connections.
- How the library handles exceeding connection limits via pruning.
- Per-peer connection limit enforcement and adjustment during runtime.
- Observing what happens when connection limits are hit.

**How to Run:**

```bash
python examples/connection_management/connection_limits_example.py
```

______________________________________________________________________

### 2. Rate Limiting ([rate_limiting_example.py](rate_limiting_example.py))

**What it Shows:**

- Configuration of rate limiting (number of new connections allowed per second per host).
- How rate limiting can mitigate flooding and DoS scenarios.
- Customizing thresholds and handling connections that exceed limits.

**How to Run:**

```bash
python examples/connection_management/rate_limiting_example.py
```

______________________________________________________________________

### 3. Allow/Deny Lists ([allow_deny_lists_example.py](allow_deny_lists_example.py))

**What it Shows:**

- Setting up explicit allow (whitelist) and deny (blacklist) lists for IP addresses.
- Support for CIDR ranges to cover networks, not just single IPs.
- How precedence rules are applied when an address matches both.
- Effectively blocking or explicitly permitting traffic.

**How to Run:**

```bash
python examples/connection_management/allow_deny_lists_example.py
```

______________________________________________________________________

### 4. Connection State Monitoring ([connection_state_example.py](connection_state_example.py))

**What it Shows:**

- How to track and query the state of connections (Pending, Open, Closing, Closed).
- Retrieving connection lifecycle information.
- Reacting to changes in connection status, useful for monitoring and debugging.

**How to Run:**

```bash
python examples/connection_management/connection_state_example.py
```

______________________________________________________________________

### 5. Comprehensive Scenarios ([comprehensive_example.py](comprehensive_example.py))

**What it Shows:**

- Combining connection limits, rate limiting, allow/deny lists and monitoring for production-grade setups.
- Example configurations for high-throughput and secure environments.
- Integration of monitoring and recommended operational practices.

**How to Run:**

```bash
python examples/connection_management/comprehensive_example.py
```

______________________________________________________________________

## Key Features Demonstrated

Each example covers one or more of these advanced connection management features:

- **Connection Limits:**
  Set maximum total connections, per-peer limits, and observe automatic pruning (oldest, least valuable, etc.).

- **Rate Limiting:**
  Prevent abuse by throttling inbound connection attempts per host (IP). Thresholds are configurable.

- **Allow/Deny Lists:**
  Restrict connections at the IP or CIDR level, enforcing security and access control policies. Deny list rules take precedence.

- **Connection State Monitoring:**
  Track connection states and events, query connection info, and register for lifecycle notifications.

______________________________________________________________________

## Example Configuration

All scripts use the `ConnectionConfig` object, which centralizes connection management options:

```python
ConnectionConfig(
    # Connection Limits
    max_connections=300,
    max_connections_per_peer=3,
    max_parallel_dials=100,
    max_dial_queue_length=500,
    max_incoming_pending_connections=10,

    # Rate Limiting
    inbound_connection_threshold=5,  # Connections/sec per host

    # Security and Access
    allow_list=["10.0.0.0/8"],
    deny_list=["192.168.1.100"],

    # Timeouts and Reconnection
    dial_timeout=10.0,
    connection_close_timeout=1.0,
    reconnect_retries=5,
    reconnect_retry_interval=1.0,
    reconnect_backoff_factor=2.0,
)
```

Refer to each example script for concrete usage.

______________________________________________________________________

## How to Run All Examples

Run each script individually to see the associated feature in action:

```bash
python examples/connection_management/connection_limits_example.py
python examples/connection_management/rate_limiting_example.py
python examples/connection_management/allow_deny_lists_example.py
python examples/connection_management/connection_state_example.py
python examples/connection_management/comprehensive_example.py
```

______________________________________________________________________

## Testing

Comprehensive test cases covering these examples are located in:

```
tests/examples/connection_management/
```

______________________________________________________________________

## Best Practices

- **Set conservative connection and rate limits** to suit your hardware and expected network load.
- **Utilize allow/deny lists** to restrict access to trusted peers and block known bad actors.
- **Monitor connection states** and log lifecycle events for debugging and health assessment.
- **Tune configuration options** as your deployment environment and security needs evolve.

______________________________________________________________________

## References

- [Connection Management Review](../../CONNECTION_MANAGEMENT_REVIEW.md) — in-depth comparison and explanation of connection management across SDKs.
- [ConnectionConfig Documentation](../../libp2p/network/config.py)
- [Connection Pruner Implementation](../../libp2p/network/connection_pruner.py)
- [Connection Gate/Rate Limiter Details](../../libp2p/network/connection_gate.py)

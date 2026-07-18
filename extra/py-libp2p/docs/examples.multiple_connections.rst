Multiple Connections Per Peer
=============================

This example demonstrates how to use the multiple connections per peer feature in py-libp2p.

Overview
--------

The multiple connections per peer feature allows a libp2p node to maintain multiple network connections to the same peer. This provides several benefits:

- **Improved reliability**: If one connection fails, others remain available
- **Better performance**: Load can be distributed across multiple connections
- **Enhanced throughput**: Multiple streams can be created in parallel
- **Fault tolerance**: Redundant connections provide backup paths

Configuration
-------------

The feature is configured through the `ConnectionConfig` class:

.. code-block:: python

    from libp2p.network.swarm import ConnectionConfig

    # Default configuration
    config = ConnectionConfig()
    print(f"Max connections per peer: {config.max_connections_per_peer}")
    print(f"Load balancing strategy: {config.load_balancing_strategy}")

    # Custom configuration
    custom_config = ConnectionConfig(
        max_connections_per_peer=5,
        connection_timeout=60.0,
        load_balancing_strategy="least_loaded"
    )

Load Balancing Strategies
-------------------------

Two load balancing strategies are available:

**Round Robin** (default)
    Cycles through connections in order, distributing load evenly.

**Least Loaded**
    Selects the connection with the fewest active streams.

API Usage
---------

The new API provides direct access to multiple connections:

.. code-block:: python

    from libp2p import new_swarm

    # Create swarm with multiple connections support
    swarm = new_swarm()

    # Dial a peer - returns list of connections
    connections = await swarm.dial_peer(peer_id)
    print(f"Established {len(connections)} connections")

    # Get all connections to a peer
    peer_connections = swarm.get_connections(peer_id)

    # Get all connections (across all peers)
    all_connections = swarm.get_connections()

    # Get the complete connections map
    connections_map = swarm.get_connections_map()

    # Backward compatibility - get single connection
    single_conn = swarm.get_connection(peer_id)

Backward Compatibility
----------------------

Existing code continues to work through backward compatibility features:

.. code-block:: python

    # Legacy 1:1 mapping (returns first connection for each peer)
    legacy_connections = swarm.connections_legacy

    # Single connection access (returns first available connection)
    conn = swarm.get_connection(peer_id)

Example
-------

A complete working example is available in the `examples/doc-examples/multiple_connections_example.py` file.

Production Configuration
-------------------------

For production use, consider these settings:

**RetryConfig Parameters**

The `RetryConfig` class controls connection retry behavior with exponential backoff:

- **max_retries**: Maximum number of retry attempts before giving up (default: 3)
- **initial_delay**: Initial delay in seconds before the first retry (default: 0.1s)
- **max_delay**: Maximum delay cap to prevent excessive wait times (default: 30.0s)
- **backoff_multiplier**: Exponential backoff multiplier - each retry multiplies delay by this factor (default: 2.0)
- **jitter_factor**: Random jitter (0.0-1.0) to prevent synchronized retries (default: 0.1)

**ConnectionConfig Parameters**

The `ConnectionConfig` class manages multi-connection behavior:

- **max_connections_per_peer**: Maximum connections allowed to a single peer (default: 3)
- **connection_timeout**: Timeout for establishing new connections in seconds (default: 30.0s)
- **load_balancing_strategy**: Strategy for distributing streams ("round_robin" or "least_loaded")

**Load Balancing Strategies Explained**

- **round_robin**: Cycles through connections in order, distributing load evenly. Simple and predictable.
- **least_loaded**: Selects the connection with the fewest active streams. Better for performance but more complex.

.. code-block:: python

    from libp2p.network.swarm import ConnectionConfig, RetryConfig

    # Production-ready configuration
    retry_config = RetryConfig(
        max_retries=3,           # Maximum retry attempts before giving up
        initial_delay=0.1,       # Start with 100ms delay
        max_delay=30.0,          # Cap exponential backoff at 30 seconds
        backoff_multiplier=2.0,  # Double delay each retry (100ms -> 200ms -> 400ms)
        jitter_factor=0.1        # Add 10% random jitter to prevent thundering herd
    )

    connection_config = ConnectionConfig(
        max_connections_per_peer=3,  # Allow up to 3 connections per peer
        connection_timeout=30.0,     # 30 second timeout for new connections
        load_balancing_strategy="round_robin"  # Simple, predictable load distribution
    )

    swarm = new_swarm(
        retry_config=retry_config,
        connection_config=connection_config
    )

**How RetryConfig Works in Practice**

With the configuration above, connection retries follow this pattern:

1. **Attempt 1**: Immediate connection attempt
2. **Attempt 2**: Wait 100ms ± 10ms jitter, then retry
3. **Attempt 3**: Wait 200ms ± 20ms jitter, then retry
4. **Attempt 4**: Wait 400ms ± 40ms jitter, then retry
5. **Attempt 5**: Wait 800ms ± 80ms jitter, then retry
6. **Attempt 6**: Wait 1.6s ± 160ms jitter, then retry
7. **Attempt 7**: Wait 3.2s ± 320ms jitter, then retry
8. **Attempt 8**: Wait 6.4s ± 640ms jitter, then retry
9. **Attempt 9**: Wait 12.8s ± 1.28s jitter, then retry
10. **Attempt 10**: Wait 25.6s ± 2.56s jitter, then retry
11. **Attempt 11**: Wait 30.0s (capped) ± 3.0s jitter, then retry
12. **Attempt 12**: Wait 30.0s (capped) ± 3.0s jitter, then retry
13. **Give up**: After 12 retries (3 initial + 9 retries), connection fails

The jitter prevents multiple clients from retrying simultaneously, reducing server load.

**Parameter Tuning Guidelines**

**For Development/Testing:**
- Use lower `max_retries` (1-2) and shorter delays for faster feedback
- Example: `RetryConfig(max_retries=2, initial_delay=0.01, max_delay=0.1)`

**For Production:**
- Use moderate `max_retries` (3-5) with reasonable delays for reliability
- Example: `RetryConfig(max_retries=5, initial_delay=0.1, max_delay=60.0)`

**For High-Latency Networks:**
- Use higher `max_retries` (5-10) with longer delays
- Example: `RetryConfig(max_retries=8, initial_delay=0.5, max_delay=120.0)`

**For Load Balancing:**
- Use `round_robin` for simple, predictable behavior
- Use `least_loaded` when you need optimal performance and can handle complexity

Architecture
------------

The implementation follows the same architectural patterns as the Go and JavaScript reference implementations:

- **Core data structure**: `dict[ID, list[INetConn]]` for 1:many mapping
- **API consistency**: Methods like `get_connections()` match reference implementations
- **Load balancing**: Integrated at the API level for optimal performance
- **Backward compatibility**: Maintains existing interfaces for gradual migration

This design ensures consistency across libp2p implementations while providing the benefits of multiple connections per peer.

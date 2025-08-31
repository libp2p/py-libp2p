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

.. code-block:: python

    from libp2p.network.swarm import ConnectionConfig, RetryConfig

    # Production-ready configuration
    retry_config = RetryConfig(
        max_retries=3,
        initial_delay=0.1,
        max_delay=30.0,
        backoff_multiplier=2.0,
        jitter_factor=0.1
    )

    connection_config = ConnectionConfig(
        max_connections_per_peer=3,  # Balance performance and resources
        connection_timeout=30.0,     # Reasonable timeout
        load_balancing_strategy="round_robin"  # Predictable behavior
    )

    swarm = new_swarm(
        retry_config=retry_config,
        connection_config=connection_config
    )

Architecture
------------

The implementation follows the same architectural patterns as the Go and JavaScript reference implementations:

- **Core data structure**: `dict[ID, list[INetConn]]` for 1:many mapping
- **API consistency**: Methods like `get_connections()` match reference implementations
- **Load balancing**: Integrated at the API level for optimal performance
- **Backward compatibility**: Maintains existing interfaces for gradual migration

This design ensures consistency across libp2p implementations while providing the benefits of multiple connections per peer.

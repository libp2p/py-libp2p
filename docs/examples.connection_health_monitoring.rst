Connection Health Monitoring
============================

This example demonstrates the enhanced connection health monitoring capabilities
in Python libp2p, which provides sophisticated connection health tracking,
proactive monitoring, health-aware load balancing, and advanced metrics collection.

Overview
--------

Connection health monitoring enhances the existing multiple connections per peer
support by adding:

- **Health Metrics Tracking**: Latency, success rates, stream counts, and more
- **Proactive Health Checks**: Periodic monitoring and automatic connection replacement
- **Health-Aware Load Balancing**: Route traffic to the healthiest connections
- **Automatic Recovery**: Replace unhealthy connections automatically

Basic Setup
-----------

To enable connection health monitoring, configure the `ConnectionConfig` with
health monitoring parameters and pass it to `new_host()`:

.. code-block:: python

    from libp2p import new_host
    from libp2p.network.config import ConnectionConfig
    from libp2p.crypto.rsa import create_new_key_pair

    # Enable health monitoring
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,  # Check every 30 seconds
        ping_timeout=3.0,  # 3 second ping timeout
        min_health_threshold=0.4,  # Minimum health score
        min_connections_per_peer=2,  # Maintain at least 2 connections
        load_balancing_strategy="health_based"  # Use health-based selection
    )

    # Create host with health monitoring
    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=connection_config
    )

Configuration Options
---------------------

Health Monitoring Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **enable_health_monitoring**: Enable/disable health monitoring (default: False)
- **health_check_interval**: Interval between health checks in seconds (default: 60.0)
- **ping_timeout**: Timeout for ping operations in seconds (default: 5.0)
- **min_health_threshold**: Minimum health score (0.0-1.0) for connections (default: 0.3)
- **min_connections_per_peer**: Minimum connections to maintain per peer (default: 1)

Load Balancing Strategies
~~~~~~~~~~~~~~~~~~~~~~~~~

- **round_robin**: Simple round-robin selection (default)
- **least_loaded**: Select connection with fewest streams
- **health_based**: Select connection with highest health score
- **latency_based**: Select connection with lowest latency

Health Metrics
--------------

The system tracks various connection health metrics:

**Basic Metrics:**
- **Ping Latency**: Response time for health checks
- **Success Rate**: Percentage of successful operations
- **Stream Count**: Number of active streams
- **Connection Age**: How long the connection has been established
- **Health Score**: Overall health rating (0.0 to 1.0)

**Advanced Metrics:**
- **Bandwidth Usage**: Real-time bandwidth tracking with time windows
- **Error History**: Detailed error tracking with timestamps
- **Connection Events**: Lifecycle event logging (establishment, closure, etc.)
- **Connection Stability**: Error rate-based stability scoring
- **Peak/Average Bandwidth**: Performance trend analysis

Host-Level Health Monitoring API
---------------------------------

The health monitoring features are now accessible through the high-level host API:

.. code-block:: python

    # Access health information through the host interface

    # Get health summary for a specific peer
    peer_health = host.get_connection_health(peer_id)
    print(f"Peer health: {peer_health}")

    # Get global network health summary
    network_health = host.get_network_health_summary()
    print(f"Total peers: {network_health.get('total_peers', 0)}")
    print(f"Total connections: {network_health.get('total_connections', 0)}")
    print(f"Average health: {network_health.get('average_peer_health', 0.0)}")

    # Export metrics in different formats
    json_metrics = host.export_health_metrics("json")
    prometheus_metrics = host.export_health_metrics("prometheus")

Example: Health-Based Load Balancing
------------------------------------

.. note::
   The code snippets below are excerpts showing key concepts. For complete
   runnable examples, see ``examples/health-monitoring/basic_example.py``.

.. code-block:: python

    from libp2p import new_host
    from libp2p.network.config import ConnectionConfig
    from libp2p.crypto.rsa import create_new_key_pair

    # Configure for production use with health-based load balancing
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        max_connections_per_peer=5,  # More connections for redundancy
        health_check_interval=120.0,  # Less frequent checks in production
        ping_timeout=10.0,  # Longer timeout for slow networks
        min_health_threshold=0.6,  # Higher threshold for production
        min_connections_per_peer=3,  # Maintain more connections
        load_balancing_strategy="health_based"  # Prioritize healthy connections
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=connection_config
    )

    # Use host as normal - health monitoring works transparently
    # In your async main() function:
    #   async with host.run(listen_addrs=["/ip4/127.0.0.1/tcp/0"]):
    #       # Health monitoring and load balancing happen automatically
    #       stream = await host.new_stream(peer_id, ["/echo/1.0.0"])

Example: Advanced Health Monitoring
------------------------------------

The enhanced health monitoring provides advanced capabilities:

.. code-block:: python

    from libp2p import new_host
    from libp2p.network.config import ConnectionConfig
    from libp2p.crypto.rsa import create_new_key_pair

    # Advanced health monitoring with comprehensive tracking
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=15.0,  # More frequent checks
        ping_timeout=2.0,  # Faster ping timeout
        min_health_threshold=0.5,  # Higher threshold
        min_connections_per_peer=2,
        load_balancing_strategy="health_based",
        # Advanced health scoring configuration
        latency_weight=0.4,
        success_rate_weight=0.4,
        stability_weight=0.2,
        max_ping_latency=1000.0,  # ms
        min_ping_success_rate=0.7,
        max_failed_streams=5
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=connection_config
    )

    # Access advanced health metrics through host API
    # In your async main() function:
    #   async with host.run(listen_addrs=["/ip4/127.0.0.1/tcp/0"]):
    #       peer_health = host.get_connection_health(peer_id)
    #       global_health = host.get_network_health_summary()
    #       json_metrics = host.export_health_metrics("json")
    #       prometheus_metrics = host.export_health_metrics("prometheus")

Example: Latency-Based Load Balancing
-------------------------------------

.. code-block:: python

    # Optimize for lowest latency connections
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        load_balancing_strategy="latency_based",  # Route to lowest latency
        health_check_interval=30.0,
        ping_timeout=5.0,
        max_connections_per_peer=3
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=connection_config
    )

    # Streams will automatically route to lowest latency connections

Example: Disabling Health Monitoring
------------------------------------

For performance-critical scenarios, health monitoring can be disabled:

.. code-block:: python

    # Disable health monitoring for maximum performance
    connection_config = ConnectionConfig(
        enable_health_monitoring=False,
        load_balancing_strategy="round_robin"  # Fall back to simple strategy
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=connection_config
    )

    # Host operates with minimal overhead, no health monitoring

Backwards Compatibility
-----------------------

Health monitoring is fully backwards compatible:

.. code-block:: python

    # Existing code continues to work unchanged
    host = new_host()  # Uses default configuration (health monitoring disabled)

    # Only when you explicitly enable it does health monitoring activate
    config = ConnectionConfig(enable_health_monitoring=True)
    host_with_health = new_host(connection_config=config)

Running the Example
-------------------

To run the connection health monitoring example:

.. code-block:: bash

    python examples/health-monitoring/basic_example.py

This will demonstrate:

1. Basic health monitoring setup through host API
2. Different load balancing strategies
3. Health metrics access and export
4. API consistency with existing examples

Benefits
--------

1. **API Consistency**: Health monitoring now works with the same high-level `new_host()` API used in all examples
2. **Production Reliability**: Prevent silent failures by detecting unhealthy connections early
3. **Performance Optimization**: Route traffic to healthiest connections, reduce latency
4. **Operational Visibility**: Monitor connection quality in real-time through host interface
5. **Automatic Recovery**: Replace degraded connections automatically
6. **Standard Compliance**: Match capabilities of Go and JavaScript libp2p implementations

Integration with Existing Code
------------------------------

Health monitoring integrates seamlessly with existing host-based code:

- All new features are optional and don't break existing code
- Health monitoring can be enabled/disabled per host instance
- Existing examples work unchanged - just add `connection_config` parameter
- Backward compatibility is maintained
- No need to switch from `new_host()` to low-level swarm APIs - the API inconsistency is fixed

**Before (Previous Implementation - API Inconsistency):**

.. code-block:: python

    # ❌ Forced to use different APIs
    host = new_host()  # High-level API for basic usage
    # Health monitoring required low-level swarm API - INCONSISTENT!

**After (Current Implementation - API Consistency):**

.. code-block:: python

    # ✅ Consistent API for all use cases
    host = new_host()  # Basic usage
    host = new_host(connection_config=config)  # Health monitoring - same API!

For more information, see the :doc:`../libp2p.network` module documentation.

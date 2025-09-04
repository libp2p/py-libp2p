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
health monitoring parameters:

.. code-block:: python

    from libp2p import new_swarm
    from libp2p.network.swarm import ConnectionConfig

    # Enable health monitoring
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,  # Check every 30 seconds
        ping_timeout=3.0,  # 3 second ping timeout
        min_health_threshold=0.4,  # Minimum health score
        min_connections_per_peer=2,  # Maintain at least 2 connections
        load_balancing_strategy="health_based"  # Use health-based selection
    )

    # Create swarm with health monitoring
    swarm = new_swarm(connection_config=connection_config)

Configuration Options
---------------------

Health Monitoring Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **enable_health_monitoring**: Enable/disable health monitoring (default: True)
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

Example: Health-Based Load Balancing
------------------------------------

.. code-block:: python

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

    swarm = new_swarm(connection_config=connection_config)

Example: Advanced Health Monitoring
--------------------------------------------

The enhanced health monitoring provides advanced capabilities:

.. code-block:: python

    # Advanced health monitoring with comprehensive tracking
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=15.0,  # More frequent checks
        ping_timeout=2.0,  # Faster ping timeout
        min_health_threshold=0.5,  # Higher threshold
        min_connections_per_peer=2,
        load_balancing_strategy="health_based"
    )

    swarm = new_swarm(connection_config=connection_config)

    # Access advanced health metrics
    peer_health = swarm.get_peer_health_summary(peer_id)
    global_health = swarm.get_global_health_summary()

    # Export metrics in different formats
    json_metrics = swarm.export_health_metrics("json")
    prometheus_metrics = swarm.export_health_metrics("prometheus")

Example: Disabling Health Monitoring
------------------------------------

For performance-critical scenarios, health monitoring can be disabled:

.. code-block:: python

    # Disable health monitoring for maximum performance
    connection_config = ConnectionConfig(
        enable_health_monitoring=False,
        load_balancing_strategy="round_robin"  # Fall back to simple strategy
    )

    swarm = new_swarm(connection_config=connection_config)

Running the Example
-------------------

To run the connection health monitoring example:

.. code-block:: bash

    python examples/doc-examples/connection_health_monitoring_example.py

This will demonstrate:
1. Basic health monitoring setup
2. Different load balancing strategies
3. Custom health monitoring configuration
4. Disabling health monitoring

Benefits
--------

1. **Production Reliability**: Prevent silent failures by detecting unhealthy connections early
2. **Performance Optimization**: Route traffic to healthiest connections, reduce latency
3. **Operational Visibility**: Monitor connection quality in real-time
4. **Automatic Recovery**: Replace degraded connections automatically
5. **Compliance**: Match capabilities of Go and JavaScript libp2p implementations

Integration with Existing Code
------------------------------

Health monitoring integrates seamlessly with existing multiple connections support:

- All new features are optional and don't break existing code
- Health monitoring can be enabled/disabled per swarm instance
- Existing load balancing strategies continue to work
- Backward compatibility is maintained

For more information, see the :doc:`../libp2p.network` module documentation.

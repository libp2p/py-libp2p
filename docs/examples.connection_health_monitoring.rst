Connection Health Monitoring Examples
=======================================

Runnable examples for the opt-in connection health monitor. For the full user
guide (configuration reference, API shapes, operator notes), see
:doc:`connection_health_monitoring`.

Overview
--------

Connection health monitoring enhances multiple-connections-per-peer support with:

- Health metrics (latency, success rate, stream counts, ``health_score``)
- Periodic ``/ipfs/ping/1.0.0`` probes per connection
- Dial-first unhealthy connection replacement (skips ConnMgr Protect)
- Health-aware load balancing (``health_based``, ``latency_based``)

Basic setup
-----------

.. code-block:: python

    from libp2p import new_host
    from libp2p.network.config import ConnectionConfig
    from libp2p.crypto.rsa import create_new_key_pair

    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        ping_timeout=3.0,
        min_health_threshold=0.4,
        min_connections_per_peer=2,
        load_balancing_strategy="health_based",
    )

    host = new_host(
        key_pair=create_new_key_pair(),
        connection_config=connection_config,
    )

Load balancing strategies
~~~~~~~~~~~~~~~~~~~~~~~~~

- **best** — prefer direct connections, then fewer streams (default)
- **round_robin** — rotate across connections
- **least_loaded** — fewest open streams
- **health_based** — highest ``health_score``
- **latency_based** — lowest ping latency

Host API (snippet)
------------------

.. code-block:: python

    peer_health = host.get_connection_health(peer_id)
    network_health = host.get_network_health_summary()
    json_metrics = host.export_health_metrics("json")
    prometheus_metrics = host.export_health_metrics("prometheus")

Running the examples
--------------------

Live multi-peer demo:

.. code-block:: bash

    python -m examples.health_monitoring.live_demo
    python -m examples.health_monitoring.live_demo --peers 10 --scenario all
    python -m examples.health_monitoring.live_demo --gui tui
    python -m examples.health_monitoring.live_demo --gui web --gui-port 8765
    health-monitoring-demo --peers 10 --scenario healthy,protect

Config walkthrough (no connections):

.. code-block:: bash

    python examples/health_monitoring/basic_example.py

See :doc:`connection_health_monitoring` for all ``ConnectionConfig`` health
fields and tuning notes.

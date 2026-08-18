Connection Health Monitoring
============================

py-libp2p ships an **opt-in** connection health monitor as a Python-local QoS
layer. It is **disabled by default** and does not change wire-protocol behavior
for peers that do not enable it.

See also:

- :doc:`examples.connection_health_monitoring` — runnable examples and CLI
- :doc:`libp2p.network.health` — module API reference
- :doc:`examples.health_monitoring` — example package automodule

Overview
--------

When enabled via ``ConnectionConfig.enable_health_monitoring``, the swarm runs
``ConnectionHealthMonitor``, which:

- Probes **each connection** periodically using ``/ipfs/ping/1.0.0`` (not
  ``PingService.ping(peer_id)``, which selects the best connection per peer).
- Maintains per-connection metrics and a composite ``health_score`` (0.0–1.0).
- Replaces persistently unhealthy connections using **dial-first** semantics
  (a replacement must succeed before the old connection is dropped).
- Skips auto-replacement for ConnMgr **Protect** peers (``tag_store``).
- Integrates with load-balancing strategies ``health_based`` and
  ``latency_based`` for outbound stream selection.

Relationship to other py-libp2p features
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **ConnMgr** (watermarks, trim, Protect/tags): health replace respects Protect;
  trimming is unchanged.
- **Load balancing** (``ConnectionConfig.load_balancing_strategy``): ``best``,
  ``round_robin``, ``least_loaded``, ``health_based``, ``latency_based``.
- **Peerstore**: optional RTT recording into LatencyEWMA after successful pings.

When to enable
--------------

Enable health monitoring when you:

- Run multiple connections per peer and want health-aware routing.
- Need visibility into connection quality (latency, success rate, scores).
- Want automatic dial-first replacement of degraded paths.

Leave it disabled (default) for minimal overhead or when you manage connectivity
entirely at the application layer.

Configuration reference
-----------------------

All fields live on ``libp2p.network.config.ConnectionConfig``.

Core toggle
~~~~~~~~~~~

``enable_health_monitoring`` (``bool``, default ``False``)
    Master switch for the monitor service and health data structures.

Timing
~~~~~~

``health_initial_delay`` (``float``, default ``60.0`` seconds)
    Delay before the first monitoring cycle (avoids startup noise).

``health_warmup_window`` (``float``, default ``5.0`` seconds)
    Skip checks on very new connections.

``health_check_interval`` (``float``, default ``60.0`` seconds)
    Period between full connection scan cycles.

``ping_timeout`` (``float``, default ``5.0`` seconds)
    Overall timeout for a single connection ping probe.

Thresholds and replacement
~~~~~~~~~~~~~~~~~~~~~~~~~~

``min_health_threshold`` (``float``, default ``0.3``)
    Score below which a connection counts as unhealthy.

``min_connections_per_peer`` (``int``, default ``1``)
    Minimum connections to keep; replace is blocked unless critically unhealthy.

``max_ping_latency`` (``float``, default ``1000.0`` ms)
    Maximum acceptable ping latency before marking unhealthy.

``min_ping_success_rate`` (``float``, default ``0.7``)
    Minimum ping success rate before marking unhealthy.

``max_failed_streams`` (``int``, default ``5``)
    Failed stream count threshold.

``unhealthy_grace_period`` (``int``, default ``3``)
    Consecutive unhealthy evaluations before replace.

``critical_health_threshold`` (``float``, default ``0.1``)
    Allows replace even at ``min_connections_per_peer`` when score is critical.

Scoring weights
~~~~~~~~~~~~~~~

``latency_weight`` (``float``, default ``0.4``)
    Weight for latency in ``health_score``.

``success_rate_weight`` (``float``, default ``0.4``)
    Weight for ping success rate.

``stability_weight`` (``float``, default ``0.2``)
    Weight for connection stability.

Probe behavior (issue #1453)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``skip_ping_when_streams_open`` (``bool``, default ``False``)
    When ``True``, skip probes on busy connections (legacy behavior). Default
    probes even when application streams are open.

``record_ping_latency_in_peerstore`` (``bool``, default ``True``)
    Record successful ping RTT into peerstore LatencyEWMA (seconds).

``abort_connection_on_ping_failure`` (``bool``, default ``False``)
    When ``True``, close the probed connection immediately after a failed ping.
    Replacement rules still apply on later ticks; Protect applies to replace,
    not to this local abort.

Host and Swarm API
------------------

All methods are available on ``IHost`` (delegates to swarm when monitoring is
enabled).

``get_connection_health(peer_id) -> dict``
    Per-peer summary: connection count, average score/latency/success rate,
    per-connection details via ``connections`` list.

``get_network_health_summary() -> dict``
    Global summary: ``total_peers``, ``total_connections``,
    ``average_peer_health``, ``peers_with_issues``, ``peer_details``.

``export_health_metrics(format="json"|"prometheus") -> str``
    JSON export mirrors ``get_network_health_summary()`` structure.
    Prometheus export exposes gauges such as ``libp2p_peers_total``,
    ``libp2p_connections_total``, ``libp2p_average_peer_health``,
    ``libp2p_peers_with_issues``.

``get_health_monitor_status() -> dict`` (async)
    Service status: ``enabled``, ``monitoring_task_started``,
    ``check_interval_seconds``, connection/peer counts.

Operator guide
--------------

Enable on a host
~~~~~~~~~~~~~~~~

.. code-block:: python

    from libp2p import new_host
    from libp2p.network.config import ConnectionConfig

    config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=30.0,
        load_balancing_strategy="health_based",
    )
    host = new_host(connection_config=config)

When auto-replace runs vs is skipped
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Replace runs when thresholds fail for ``unhealthy_grace_period`` consecutive
checks **and**:

- The connection has no open streams (active traffic blocks replace).
- The peer is **not** ConnMgr-protected.
- Dial-first replacement succeeds.
- Either above ``min_connections_per_peer`` after removal, or critically unhealthy.

Live demo and GUI
~~~~~~~~~~~~~~~~~

Console script (after install):

.. code-block:: bash

    health-monitoring-demo --peers 10 --scenario all

Module invocation:

.. code-block:: bash

    python -m examples.health_monitoring.live_demo --peers 10 --scenario healthy,protect
    python -m examples.health_monitoring.live_demo --gui tui
    python -m examples.health_monitoring.live_demo --gui web --gui-port 8765

``--gui tui`` opens a terminal table; ``--gui web`` serves HTML plus
``/api/summary`` (JSON) and ``/api/metrics?format=prometheus``.

Config-only walkthrough (no connections):

.. code-block:: bash

    python examples/health_monitoring/basic_example.py

Reading health summaries
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    summary = host.get_network_health_summary()
    peer = host.get_connection_health(some_peer_id)
    print(host.export_health_metrics("json"))

Protect a peer from auto-replace (ConnMgr API / ``tag_store.Protect``) before
expecting replace to skip that peer.

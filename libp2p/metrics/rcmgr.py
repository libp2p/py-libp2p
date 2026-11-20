"""
Read-only prometheus bridge over the resource manager's internal metrics.

The rcmgr keeps its own array-based counters (``libp2p/rcmgr/metrics.py``)
and already ships a full go-libp2p-compatible exporter
(``libp2p/rcmgr/prometheus_exporter.py``) that uses a *private* registry.
:class:`RcMgrMetrics` instead exposes the same summary on the *default*
prometheus registry so it appears on the shared ``/metrics`` endpoint
served by :class:`libp2p.metrics.metrics.Metrics`.
"""

from typing import Any, Iterable

from prometheus_client.core import Collector, GaugeMetricFamily

_BLOCK_RESOURCES = ("connections", "memory", "streams")


class RcMgrMetrics(Collector):
    """Collect rcmgr summary values into go-libp2p-style gauge families."""

    def __init__(self, resource_manager: Any) -> None:
        self._resource_manager = resource_manager

    def collect(self) -> Iterable[GaugeMetricFamily]:
        metrics = getattr(self._resource_manager, "metrics", None)
        if metrics is None or not hasattr(metrics, "get_summary"):
            return

        summary = metrics.get_summary()
        try:
            conns = summary["connections"]
            streams = summary["streams"]
            memory = summary["memory"]
            blocks = summary["blocks"]
        except KeyError:
            return

        connections = GaugeMetricFamily(
            "libp2p_rcmgr_connections",
            "Number of connections managed by the resource manager",
            labels=["dir"],
        )
        for direction in ("inbound", "outbound", "total", "peak"):
            connections.add_metric([direction], conns.get(direction, 0))
        yield connections

        connection_streams = GaugeMetricFamily(
            "libp2p_rcmgr_streams",
            "Number of streams managed by the resource manager",
            labels=["dir"],
        )
        for direction in ("inbound", "outbound", "total", "peak"):
            connection_streams.add_metric([direction], streams.get(direction, 0))
        yield connection_streams

        memory_usage = GaugeMetricFamily(
            "libp2p_rcmgr_memory",
            "Memory usage as reported to the resource manager",
            labels=["kind"],
        )
        memory_usage.add_metric(["current"], memory.get("current", 0))
        memory_usage.add_metric(["peak"], memory.get("peak", 0))
        yield memory_usage

        blocked = GaugeMetricFamily(
            "libp2p_rcmgr_blocked_resources",
            "Resources blocked by the resource manager",
            labels=["resource"],
        )
        for resource in _BLOCK_RESOURCES:
            blocked.add_metric([resource], blocks.get(resource, 0))
        yield blocked

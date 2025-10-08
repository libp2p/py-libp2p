from collections import defaultdict
from dataclasses import dataclass, field
import time
from typing import Any, Union


@dataclass
class ResourceMetrics:
    """Metrics for a specific resource type."""

    allowed: int = 0
    blocked: int = 0
    current_usage: int = 0
    peak_usage: int = 0
    last_updated: float = field(default_factory=time.time)


class Metrics:
    ## time may not be necessary, but maybe useful for some metrics
    ## some implementation for remaining blocked services might be left
    def __init__(self) -> None:
        self.data: dict[str, Union[float, str]] = {}
        self.resource_metrics: dict[str, ResourceMetrics] = defaultdict(ResourceMetrics)
        self._start_time = time.time()

    def record(self, key: str, value: Union[float, str]) -> None:
        self.data[key] = value

    def get(self, key: str) -> float:
        value = self.data.get(key, 0.0)
        return float(value) if isinstance(value, (int, float, str)) else 0.0

    def increment(self, key: str, delta: float = 1.0) -> None:
        current = self.data.get(key, 0.0)
        self.data[key] = (float(current) if isinstance(current, (int, float, str)) else 0.0) + delta

    def block_memory(self, size: int) -> None:
        self.resource_metrics["memory"].blocked += 1
        self.increment("memory_blocks_total")
        self.record("last_memory_block_size", size)
        self.record("last_memory_block_time", time.time())

    def allow_memory(self, size: int) -> None:
        metrics = self.resource_metrics["memory"]
        metrics.allowed += 1
        metrics.current_usage += size
        metrics.peak_usage = max(metrics.peak_usage, metrics.current_usage)
        metrics.last_updated = time.time()

        self.increment("memory_allocations_total")
        self.record("memory_current_usage", metrics.current_usage)
        self.record("memory_peak_usage", metrics.peak_usage)

    def release_memory(self, size: int) -> None:
        """Record memory release."""
        metrics = self.resource_metrics["memory"]
        metrics.current_usage = max(0, metrics.current_usage - size)
        metrics.last_updated = time.time()

        self.record("memory_current_usage", metrics.current_usage)

    ## Stream Metrics

    def block_stream(self, peer_id: str, direction: str) -> None:
        """Record a blocked stream."""
        key = f"streams_{direction}"
        self.resource_metrics[key].blocked += 1
        self.increment(f"{key}_blocks_total")
        self.record(f"last_{key}_block_peer", peer_id)
        self.record(f"last_{key}_block_time", time.time())

    def allow_stream(self, peer_id: str, direction: str) -> None:
        """Record an allowed stream."""
        key = f"streams_{direction}"
        metrics = self.resource_metrics[key]
        metrics.allowed += 1
        metrics.current_usage += 1
        metrics.peak_usage = max(metrics.peak_usage, metrics.current_usage)
        metrics.last_updated = time.time()

        self.increment(f"{key}_total")
        self.record(f"{key}_current", metrics.current_usage)
        self.record(f"{key}_peak", metrics.peak_usage)

    def remove_stream(self, direction: str) -> None:
        """Record stream removal."""
        key = f"streams_{direction}"
        metrics = self.resource_metrics[key]
        metrics.current_usage = max(0, metrics.current_usage - 1)
        metrics.last_updated = time.time()

        self.record(f"{key}_current", metrics.current_usage)

    ## Connection Metrics

    def block_conn(self, direction: str, use_fd: bool) -> None:
        """Record a blocked connection."""
        key = f"conns_{direction}"
        self.resource_metrics[key].blocked += 1
        self.increment(f"{key}_blocks_total")
        self.record(f"last_{key}_block_time", time.time())

        if use_fd:
            self.resource_metrics["fd"].blocked += 1
            self.increment("fd_blocks_total")

    def allow_conn(self, direction: str, use_fd: bool) -> None:
        key = f"conns_{direction}"
        metrics = self.resource_metrics[key]
        metrics.allowed += 1
        metrics.current_usage += 1
        metrics.peak_usage = max(metrics.peak_usage, metrics.current_usage)
        metrics.last_updated = time.time()

        self.increment(f"{key}_total")
        self.record(f"{key}_current", metrics.current_usage)
        self.record(f"{key}_peak", metrics.peak_usage)

        if use_fd:
            fd_metrics = self.resource_metrics["fd"]
            fd_metrics.allowed += 1
            fd_metrics.current_usage += 1
            fd_metrics.peak_usage = max(fd_metrics.peak_usage, fd_metrics.current_usage)
            fd_metrics.last_updated = time.time()

            self.increment("fd_total")
            self.record("fd_current", fd_metrics.current_usage)
            self.record("fd_peak", fd_metrics.peak_usage)

    def remove_conn(self, direction: str, use_fd: bool) -> None:
        key = f"conns_{direction}"
        metrics = self.resource_metrics[key]
        metrics.current_usage = max(0, metrics.current_usage - 1)
        metrics.last_updated = time.time()

        self.record(f"{key}_current", metrics.current_usage)

        if use_fd:
            fd_metrics = self.resource_metrics["fd"]
            fd_metrics.current_usage = max(0, fd_metrics.current_usage - 1)
            fd_metrics.last_updated = time.time()

            self.record("fd_current", fd_metrics.current_usage)

    def allow_peer(self, peer_id: str) -> None:
        self.increment("peer_connections_total")
        self.record("last_peer_connected", peer_id)
        self.record("last_peer_connect_time", time.time())

    def allow_protocol(self, protocol: str) -> None:
        self.increment("protocol_streams_total")
        self.record("last_protocol_stream", protocol)
        self.record("last_protocol_stream_time", time.time())

    def allow_service(self, service: str) -> None:
        """Record an allowed service stream."""
        self.increment("service_streams_total")
        self.record("last_service_stream", service)
        self.record("last_service_stream_time", time.time())

    def block_protocol_peer(self, protocol: str, peer_id: str) -> None:
        """Record a blocked protocol-peer stream."""
        self.increment("protocol_peer_blocks_total")
        self.record("last_protocol_peer_block", f"{protocol}:{peer_id}")
        self.record("last_protocol_peer_block_time", time.time())

    def block_service_peer(self, service: str, peer_id: str) -> None:
        """Record a blocked service-peer stream."""
        self.increment("service_peer_blocks_total")
        self.record("last_service_peer_block", f"{service}:{peer_id}")
        self.record("last_service_peer_block_time", time.time())

    def get_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "uptime": time.time() - self._start_time,
            "resource_metrics": {},
            "totals": {},
        }

        # Resource metrics summary
        for resource_type, metrics in self.resource_metrics.items():
            if "resource_metrics" not in summary:
                summary["resource_metrics"] = {}
            summary["resource_metrics"][resource_type] = {
                "allowed": metrics.allowed,
                "blocked": metrics.blocked,
                "current_usage": metrics.current_usage,
                "peak_usage": metrics.peak_usage,
                "success_rate": (
                    metrics.allowed / (metrics.allowed + metrics.blocked)
                    if (metrics.allowed + metrics.blocked) > 0
                    else 1.0
                ),
            }

        # Total counters
        for key, value in self.data.items():
            if "_total" in key or "_current" in key or "_peak" in key:
                if "totals" not in summary:
                    summary["totals"] = {}
                summary["totals"][key] = value

        return summary

    def reset(self) -> None:
        """Reset all metrics."""
        self.data.clear()
        self.resource_metrics.clear()
        self._start_time = time.time()

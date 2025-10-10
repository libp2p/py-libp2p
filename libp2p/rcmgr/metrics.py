from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .limits import Direction


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
        """Initialize the BasicMetrics collector."""
        self.data: dict[str, float | str] = {}
        self.resource_metrics: dict[str, ResourceMetrics] = defaultdict(ResourceMetrics)
        self._start_time = time.time()

    def record(self, key: str, value: float | str) -> None:
        self.data[key] = value

    def get(self, key: str, default: float = 0.0) -> float:
        value = self.data.get(key, default)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return float(value) if isinstance(value, (int, float)) else default

    def increment(self, key: str, delta: float = 1.0) -> None:
        current = self.data.get(key, 0.0)
        current = float(current) if isinstance(current, (int, float, str)) else 0.0
        self.data[key] = current + delta

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

    def record_memory(self, scope_name: str, size: int | str) -> None:
        """Record memory usage for a specific scope."""
        self.record(f"memory_{scope_name}", size)
        self.record(f"memory_{scope_name}_time", time.time())

    def get_memory(self, scope_name: str) -> float | str:
        """Get memory usage for a specific scope."""
        value = self.data.get(f"memory_{scope_name}", 0)
        return value

    def increment_memory(self, scope_name: str, delta: int) -> None:
        """Increment memory usage for a specific scope by delta amount."""
        current_key = f"memory_{scope_name}"
        current = self.get(current_key, 0)
        new_value = max(0.0, current + delta)  # Don't allow negative memory
        self.record(current_key, new_value)
        self.record(f"memory_{scope_name}_time", time.time())

    ## File Descriptor Metrics

    def record_fd(self, scope_name: str, count: int) -> None:
        """Record file descriptor count for a specific scope."""
        self.record(f"fd_{scope_name}", count)
        self.record(f"fd_{scope_name}_time", time.time())

    def get_fd(self, scope_name: str) -> int:
        """Get file descriptor count for a specific scope."""
        return int(self.get(f"fd_{scope_name}"))

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

    def record_streams(self, scope_name: str, total: int, inbound: int) -> None:
        """Record stream counts for a specific scope."""
        outbound = total - inbound
        self.record(f"streams_{scope_name}_inbound", inbound)
        self.record(f"streams_{scope_name}_outbound", outbound)
        self.record(f"streams_{scope_name}_total", total)
        self.record(f"streams_{scope_name}_time", time.time())

    def get_streams(self, scope_name: str) -> dict[str, int]:
        """Get stream counts for a specific scope."""
        inbound = int(self.get(f"streams_{scope_name}_inbound"))
        outbound = int(self.get(f"streams_{scope_name}_outbound"))
        total = int(self.get(f"streams_{scope_name}_total"))
        return {"inbound": inbound, "outbound": outbound, "total": total}

    def add_stream(self, scope_name: str, direction: Direction) -> None:
        """Add a stream to the specified scope."""
        direction_str = direction.value.lower()
        # Increment the count for this scope and direction
        key = f"streams_{scope_name}_{direction_str}"
        self.increment(key)

        # Update total count
        total_key = f"streams_{scope_name}_total"
        self.increment(total_key)

        # Update timestamp
        self.record(f"streams_{scope_name}_time", time.time())

    def remove_stream(self, *args: str | Direction) -> None:
        """Remove a stream - supports both global and scope-specific removal."""
        if len(args) == 1:
            # Global removal: remove_stream(direction_str)
            direction = args[0]
            key = f"streams_{direction}"
            metrics = self.resource_metrics[key]
            metrics.current_usage = max(0, metrics.current_usage - 1)
            metrics.last_updated = time.time()
            self.record(f"{key}_current", metrics.current_usage)
        elif len(args) == 2:
            # Scope-specific removal: remove_stream(scope_name, direction)
            scope_name, direction = args
            # Handle Direction enum or string safely
            try:
                # Try to access .value attribute (Direction enum)
                if hasattr(direction, "value"):
                    direction_value = getattr(direction, "value")
                    if hasattr(direction_value, "lower"):
                        direction_str = direction_value.lower()
                    else:
                        direction_str = str(direction_value).lower()
                else:
                    direction_str = str(direction).lower()
            except (AttributeError, TypeError):
                # Fallback to string conversion
                direction_str = str(direction).lower()

            # Decrement the count for this scope and direction
            key = f"streams_{scope_name}_{direction_str}"
            current = self.get(key, 0)
            self.record(key, max(0.0, current - 1))

            # Update total count
            total_key = f"streams_{scope_name}_total"
            current_total = self.get(total_key, 0)
            self.record(total_key, max(0.0, current_total - 1))
            # Update timestamp
            self.record(f"streams_{scope_name}_time", time.time())
        else:
            raise TypeError(
                f"remove_stream() takes 1 or 2 arguments but {len(args)} were given"
            )  ## Connection Metrics

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

    def record_connections(self, scope_name: str, total: int, inbound: int) -> None:
        """Record connection counts for a specific scope."""
        outbound = total - inbound
        self.record(f"connections_{scope_name}_inbound", inbound)
        self.record(f"connections_{scope_name}_outbound", outbound)
        self.record(f"connections_{scope_name}_total", total)
        self.record(f"connections_{scope_name}_time", time.time())

    def add_connection(self, scope_name: str, direction: Direction) -> None:
        """Add a connection to the specified scope."""
        direction_str = direction.value.lower()
        # Increment the count for this scope and direction
        key = f"connections_{scope_name}_{direction_str}"
        self.increment(key)

        # Update total count
        total_key = f"connections_{scope_name}_total"
        self.increment(total_key)

        # Update timestamp
        self.record(f"connections_{scope_name}_time", time.time())

    def get_connections(self, scope_name: str) -> dict[str, int]:
        """Get connection counts for a specific scope."""
        inbound = int(self.get(f"connections_{scope_name}_inbound"))
        outbound = int(self.get(f"connections_{scope_name}_outbound"))
        total = int(self.get(f"connections_{scope_name}_total"))
        return {"inbound": inbound, "outbound": outbound, "total": total}

    def remove_connection(self, scope_name: str, direction: Direction) -> None:
        """Remove a connection from the specified scope."""
        direction_str = direction.value.lower()
        # Decrement the count for this scope and direction
        key = f"connections_{scope_name}_{direction_str}"
        current = self.get(key, 0)
        self.record(key, max(0.0, current - 1))

        # Update total count
        total_key = f"connections_{scope_name}_total"
        current_total = self.get(total_key, 0)
        self.record(total_key, max(0.0, current_total - 1))
        # Update timestamp
        self.record(f"connections_{scope_name}_time", time.time())

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

        # Group metrics by scope
        scope_metrics: dict[str, dict[str, Any]] = {}

        for key, value in self.data.items():
            # Parse scope-specific metrics
            if key.startswith(("memory_", "streams_", "connections_", "fd_")):
                parts = key.split("_", 1)
                if len(parts) >= 2:
                    metric_type = parts[0]
                    scope_info = parts[1]

                    # Skip time stamps
                    if scope_info.endswith("_time"):
                        continue

                    # Extract scope name (everything before the last _direction or
                    # _property)
                    if scope_info.endswith(("_inbound", "_outbound", "_total")):
                        scope_parts = scope_info.rsplit("_", 1)
                        scope_name = scope_parts[0]
                        property_name = scope_parts[1]
                    else:
                        scope_name = scope_info
                        property_name = "total"

                    if scope_name not in scope_metrics:
                        scope_metrics[scope_name] = {}

                    if metric_type == "memory":
                        scope_metrics[scope_name]["memory"] = value
                    elif metric_type == "fd":
                        scope_metrics[scope_name]["fd"] = value
                    elif metric_type in ("streams", "connections"):
                        if metric_type not in scope_metrics[scope_name]:
                            scope_metrics[scope_name][metric_type] = {}
                        scope_metrics[scope_name][metric_type][property_name] = value

        summary["resource_metrics"] = scope_metrics

        # Original resource metrics (for backward compatibility)
        for resource_type, metrics in self.resource_metrics.items():
            # Store both with and without "global_" prefix for compatibility
            global_key = f"global_{resource_type}"
            resource_data = {
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
            summary["resource_metrics"][global_key] = resource_data
            summary["resource_metrics"][resource_type] = resource_data

        # Total counters
        for key, value in self.data.items():
            if "_total" in key or "_current" in key or "_peak" in key:
                summary["totals"][key] = value

        return summary

    def reset(self) -> None:
        """Reset all metrics."""
        self.data.clear()
        self.resource_metrics.clear()
        self._start_time = time.time()

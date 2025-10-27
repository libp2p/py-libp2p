from __future__ import annotations

import threading
from typing import Any, cast

from .allowlist import Allowlist, AllowlistConfig
from .circuit_breaker import CircuitBreaker, CircuitBreakerError
from .connection_limits import ConnectionLimits, new_connection_limits_with_defaults
from .connection_pool import ConnectionPool
from .connection_tracker import ConnectionTracker
from .exceptions import ResourceScopeClosed
from .graceful_degradation import GracefulDegradation
from .memory_limits import (
    MemoryConnectionLimits,
    new_memory_connection_limits_with_defaults,
)
from .memory_pool import MemoryPool
from .memory_stats import MemoryStatsCache
from .metrics import Direction, Metrics
from .prometheus_exporter import PrometheusExporter, create_prometheus_exporter

"""
Resource Manager implementation.
"""


class ConnectionScope:
    """Represents a resource scope for a connection. Used for tracking and cleanup."""

    def __init__(self, peer_id: str, resource_manager: ResourceManager) -> None:
        self.peer_id = peer_id
        self.resource_manager = resource_manager
        self.closed = False

    def close(self) -> None:
        if not self.closed:
            # Release the connection resource
            self.resource_manager.release_connection(self.peer_id)
            self.closed = True

    def __enter__(self) -> ConnectionScope:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()


"""
Resource Manager implementation.

This module provides the ResourceManager class for managing
libp2p resources including connections, memory, and streams.
"""


class ResourceLimits:
    """Resource limits configuration"""

    def __init__(
        self,
        max_connections: int = 1000,
        max_memory_mb: int = 512,
        max_streams: int = 10000,
    ):
        self.max_connections = max_connections
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_streams = max_streams


class ResourceManager:
    """
    Resource manager for tracking and limiting libp2p resources.

    Manages connections, memory usage, and streams with configurable limits.
    """

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        allowlist: Allowlist | None = None,
        metrics: Metrics | None = None,
        allowlist_config: AllowlistConfig | None = None,
        enable_metrics: bool = True,
        connection_limits: ConnectionLimits | None = None,
        enable_connection_tracking: bool = True,
        memory_limits: MemoryConnectionLimits | None = None,
        enable_memory_limits: bool = True,
        enable_connection_pooling: bool = True,
        enable_memory_pooling: bool = True,
        enable_circuit_breaker: bool = True,
        enable_graceful_degradation: bool = True,
        enable_prometheus: bool = False,
        prometheus_port: int = 8000,
        prometheus_exporter: PrometheusExporter | None = None,
    ) -> None:
        # Resource limits
        self.limits = limits or ResourceLimits()

        # Allowlist setup
        if allowlist is not None:
            self.allowlist = allowlist
        elif allowlist_config is not None:
            self.allowlist = Allowlist(allowlist_config)
        else:
            self.allowlist = Allowlist()

        # Metrics setup
        # Respect an explicitly provided `metrics` instance first. If not
        # provided, create one only when `enable_metrics` is True. Otherwise
        # keep metrics disabled (None).
        if metrics is not None:
            self.metrics = metrics
        elif enable_metrics:
            self.metrics = Metrics()
        else:
            self.metrics = None  # type: ignore

        # Prometheus setup
        self.prometheus_exporter: PrometheusExporter | None
        if prometheus_exporter is not None:
            self.prometheus_exporter = prometheus_exporter
        elif enable_prometheus:
            self.prometheus_exporter = create_prometheus_exporter(
                port=prometheus_port, enable_server=True
            )
        else:
            self.prometheus_exporter = None

        # Thread safety
        self._lock = threading.RLock()
        self._closed: bool = False

        # Resource tracking
        self._current_connections: int = 0
        self._current_memory: int = 0
        self._current_streams: int = 0

        # Connection tracking
        self.connection_tracker: ConnectionTracker | None = None
        if enable_connection_tracking:
            self.connection_tracker = ConnectionTracker()

        # Connection limits
        self.connection_limits = (
            connection_limits or new_connection_limits_with_defaults()
        )

        # Memory limits
        self.memory_limits = (
            memory_limits or new_memory_connection_limits_with_defaults()
        )
        self.memory_stats_cache = MemoryStatsCache()

        # Performance optimizations
        self.connection_pool: ConnectionPool[Any] | None = None
        if enable_connection_pooling:
            self.connection_pool = ConnectionPool(
                max_size=self.limits.max_connections, pre_allocate=True
            )

        self.memory_pool: MemoryPool | None = None
        if enable_memory_pooling:
            self.memory_pool = MemoryPool(
                block_size=1024 * 1024,  # 1MB blocks
                initial_blocks=100,
                max_blocks=1000,
            )

        # Production features
        self.circuit_breaker: CircuitBreaker | None = None
        if enable_circuit_breaker:
            self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60.0)

        self.graceful_degradation: GracefulDegradation | None = None
        if enable_graceful_degradation:
            self.graceful_degradation = GracefulDegradation(self)

    def _update_prometheus_metrics(self) -> None:
        """Update Prometheus metrics from internal metrics."""
        if self.prometheus_exporter and self.metrics:
            self.prometheus_exporter.update_from_metrics(self.metrics)

    def _record_blocked_resource(
        self, resource_type: str, direction: str = "unknown", scope: str = "system"
    ) -> None:
        """Record blocked resource in both internal metrics and Prometheus."""
        if self.metrics:
            self.metrics.record_block(resource_type)

        if self.prometheus_exporter:
            self.prometheus_exporter.record_blocked_resource(
                direction=direction, scope=scope, resource=resource_type
            )

    def acquire_connection(self, peer_id: str = "") -> bool:
        """Acquire a connection resource"""
        # Check circuit breaker
        if self.circuit_breaker and self.circuit_breaker.is_open():
            return False

        def _acquire() -> bool:
            with self._lock:
                if self._closed:
                    raise ResourceScopeClosed()

                # If the peer is allowlisted, bypass normal limits.

                try:
                    allowlisted: bool = False
                    if peer_id and hasattr(self, "allowlist"):
                        from libp2p.peer.id import ID

                        if isinstance(peer_id, ID):
                            pid = cast(ID, peer_id)
                        else:
                            pid = ID.from_base58(peer_id)
                        allowlisted = self.allowlist.allowed_peer(pid)
                except Exception:
                    allowlisted = False

                if (
                    not allowlisted
                    and self._current_connections >= self.limits.max_connections
                ):
                    # Try graceful degradation
                    if self.graceful_degradation:
                        if self.graceful_degradation.handle_resource_exhaustion(
                            "connections"
                        ):
                            # Retry after degradation
                            if self._current_connections >= self.limits.max_connections:
                                self._record_blocked_resource("connection", "inbound")
                                return False
                        else:
                            self._record_blocked_resource("connection", "inbound")
                            return False
                    else:
                        self._record_blocked_resource("connection", "inbound")
                        return False

                self._current_connections += 1

                # Record metrics if enabled. For allowlisted peers we still
                # record allowed connections so metrics reflect activity.
                if self.metrics:
                    self.metrics.allow_conn("inbound", use_fd=True)

                # Update Prometheus metrics
                self._update_prometheus_metrics()

                return True

        try:
            if self.circuit_breaker:
                return self.circuit_breaker.call(_acquire)
            else:
                return _acquire()
        except CircuitBreakerError:
            return False

    def release_connection(self, peer_id: str = "") -> None:
        """Release a connection resource"""
        with self._lock:
            if self._current_connections > 0:
                self._current_connections -= 1

                if self.metrics:
                    self.metrics.remove_conn("inbound", use_fd=True)

                # Update Prometheus metrics
                self._update_prometheus_metrics()

    def acquire_memory(self, size: int) -> bool:
        """Acquire memory resource"""
        # Check circuit breaker
        if self.circuit_breaker and self.circuit_breaker.is_open():
            return False

        def _acquire() -> bool:
            with self._lock:
                if self._closed:
                    raise ResourceScopeClosed()

                # Allowlist bypass: if the requesting peer/endpoint is
                # allowlisted we let them allocate memory without enforcing
                # the configured limits. Since this method doesn't receive a
                # peer id, callers that need allowlist-aware behaviour should
                # perform the check at a higher level. We still attempt a
                # best-effort check here based on a configured allowlist
                # attribute (if present) by checking an empty-string key.
                allowlisted = False
                try:
                    if hasattr(self, "allowlist"):
                        # We can't determine peer here; keep default False.
                        allowlisted = False
                except Exception:
                    allowlisted = False

                current_memory_after = self._current_memory + size
                if (
                    not allowlisted
                    and current_memory_after > self.limits.max_memory_bytes
                ):
                    # Try graceful degradation
                    if self.graceful_degradation:
                        if self.graceful_degradation.handle_resource_exhaustion(
                            "memory"
                        ):
                            # Retry after degradation
                            if (
                                self._current_memory + size
                                > self.limits.max_memory_bytes
                            ):
                                self._record_blocked_resource("memory")
                                return False
                        else:
                            self._record_blocked_resource("memory")
                            return False
                    else:
                        self._record_blocked_resource("memory")
                        return False

                self._current_memory += size

                if self.metrics:
                    self.metrics.allow_memory(size)

                # Update Prometheus metrics
                self._update_prometheus_metrics()

                return True

        try:
            if self.circuit_breaker:
                return self.circuit_breaker.call(_acquire)
            else:
                return _acquire()
        except CircuitBreakerError:
            return False

    def release_memory(self, size: int) -> None:
        """Release memory resource"""
        with self._lock:
            self._current_memory = max(0, self._current_memory - size)

            if self.metrics:
                self.metrics.release_memory(size)

            # Update Prometheus metrics
            self._update_prometheus_metrics()

    def acquire_stream(self, peer_id: str, direction: Direction) -> bool:
        """Acquire a stream resource"""
        with self._lock:
            if self._closed:
                raise ResourceScopeClosed()

            # Allowlist bypass for streams: if the peer is allowlisted, do
            # not enforce the streams limit.
            try:
                allowlisted: bool = False
                if peer_id and hasattr(self, "allowlist"):
                    from libp2p.peer.id import ID

                    if isinstance(peer_id, ID):
                        pid = cast(ID, peer_id)
                    else:
                        pid = ID.from_base58(peer_id)
                    allowlisted = self.allowlist.allowed_peer(pid)
            except Exception:
                allowlisted = False

            if not allowlisted and self._current_streams >= self.limits.max_streams:
                direction_str = (
                    "inbound" if direction == Direction.INBOUND else "outbound"
                )
                self._record_blocked_resource("stream", direction_str)
                return False

            self._current_streams += 1

            if self.metrics:
                direction_str = (
                    "inbound" if direction == Direction.INBOUND else "outbound"
                )
                # Ensure peer_id is a string for metrics
                from libp2p.peer.id import ID

                if isinstance(peer_id, ID):
                    peer_id_str = peer_id.to_base58()
                else:
                    peer_id_str = str(peer_id)
                self.metrics.allow_stream(peer_id_str, direction_str)

            # Update Prometheus metrics
            self._update_prometheus_metrics()

            return True

    def release_stream(self, peer_id: str, direction: Direction) -> None:
        """Release a stream resource"""
        with self._lock:
            if self._current_streams > 0:
                self._current_streams -= 1

                if self.metrics:
                    direction_str = (
                        "inbound" if direction == Direction.INBOUND else "outbound"
                    )
                    self.metrics.remove_stream(direction_str)

                # Update Prometheus metrics
                self._update_prometheus_metrics()

    def get_stats(self) -> dict[str, Any]:
        """Get current resource statistics"""
        with self._lock:
            stats: dict[str, Any] = {
                "connections": self._current_connections,
                "memory_bytes": self._current_memory,
                "streams": self._current_streams,
                "limits": {
                    "max_connections": self.limits.max_connections,
                    "max_memory_bytes": self.limits.max_memory_bytes,
                    "max_streams": self.limits.max_streams,
                },
            }

            # Add optimization statistics
            if self.connection_pool:
                pool_stats = self.connection_pool.get_stats()
                stats["connection_pool"] = pool_stats

            if self.memory_pool:
                memory_stats = self.memory_pool.get_stats()
                stats["memory_pool"] = memory_stats

            if self.circuit_breaker:
                breaker_stats = self.circuit_breaker.get_stats()
                stats["circuit_breaker"] = breaker_stats

            if self.graceful_degradation:
                stats["graceful_degradation"] = self.graceful_degradation.get_stats()

            return stats

    def is_resource_available(self, resource_type: str, amount: int = 1) -> bool:
        """Check if a resource is available"""
        with self._lock:
            if resource_type == "connections":
                return self._current_connections + amount <= self.limits.max_connections
            elif resource_type == "memory":
                return self._current_memory + amount <= self.limits.max_memory_bytes
            elif resource_type == "streams":
                return self._current_streams + amount <= self.limits.max_streams
            return False

    def open_connection(
        self,
        peer_id: Any | None = None,
    ) -> ConnectionScope | None:
        """
        Open a connection resource for the given peer and return a
        scope object for tracking/cleanup.
        """
        peer_id_str = str(peer_id) if peer_id is not None else ""
        acquired = self.acquire_connection(peer_id_str)
        if acquired:
            return ConnectionScope(peer_id_str, self)
        return None

    # Only one release_connection method is needed, defined above.

    def close(self) -> None:
        """Close the resource manager"""
        with self._lock:
            if self._closed:
                return
            self._closed = True

            # Reset all counters
            self._current_connections = 0
            self._current_memory = 0
            self._current_streams = 0


def new_resource_manager(
    limits: ResourceLimits | None = None,
    allowlist_config: AllowlistConfig | None = None,
    enable_metrics: bool = True,
    connection_limits: ConnectionLimits | None = None,
    enable_connection_tracking: bool = True,
    memory_limits: MemoryConnectionLimits | None = None,
    enable_memory_limits: bool = True,
    enable_connection_pooling: bool = True,
    enable_memory_pooling: bool = True,
    enable_circuit_breaker: bool = True,
    enable_graceful_degradation: bool = True,
) -> ResourceManager:
    """Create a new resource manager"""
    return ResourceManager(
        limits=limits,
        allowlist_config=allowlist_config,
        enable_metrics=enable_metrics,
        connection_limits=connection_limits,
        enable_connection_tracking=enable_connection_tracking,
        memory_limits=memory_limits,
        enable_memory_limits=enable_memory_limits,
        enable_connection_pooling=enable_connection_pooling,
        enable_memory_pooling=enable_memory_pooling,
        enable_circuit_breaker=enable_circuit_breaker,
        enable_graceful_degradation=enable_graceful_degradation,
    )

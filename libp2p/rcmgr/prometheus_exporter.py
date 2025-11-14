"""
Prometheus metrics exporter for libp2p resource manager.
"""

from __future__ import annotations

import threading

try:
    from prometheus_client import (  # type: ignore[import]
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Gauge,
        Histogram,
        generate_latest,
        start_http_server,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

from .metrics import Metrics


class PrometheusExporter:
    """
    Exports libp2p resource manager metrics in Prometheus format.

    This exporter provides metrics compatible with the go-libp2p resource manager
    format, allowing the use of existing Grafana dashboards and monitoring tools.
    """

    def __init__(
        self,
        port: int = 8000,
        registry: CollectorRegistry | None = None,
        enable_server: bool = True,
    ) -> None:
        """
        Initialize the Prometheus exporter.

        Args:
            port: HTTP port for metrics endpoint
            registry: Custom Prometheus registry (uses default if None)
            enable_server: Whether to start the HTTP server automatically

        Raises:
            ImportError: If prometheus_client is not available

        """
        if not PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client is required for Prometheus metrics export. "
                "Install with: pip install prometheus-client"
            )

        self.port = port
        self.registry = registry or CollectorRegistry()
        self.enable_server = enable_server
        self._server_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()

        # Peer tracking for histogram metrics
        self._peer_connections: dict[str, dict[str, int]] = {}
        self._peer_streams: dict[str, dict[str, int]] = {}
        self._peer_memory: dict[str, int] = {}
        self._conn_memory: dict[str, int] = {}

        # Declare metric attributes
        self.connections: Gauge
        self.streams: Gauge
        self.memory: Gauge
        self.fds: Gauge
        self.blocked_resources: Gauge
        self.peer_connections: Histogram
        self.previous_peer_connections: Histogram
        self.peer_streams: Histogram
        self.previous_peer_streams: Histogram
        self.peer_memory: Histogram
        self.previous_peer_memory: Histogram
        self.conn_memory: Histogram
        self.previous_conn_memory: Histogram

        # Initialize Prometheus metrics (compatible with go-libp2p)
        self._init_metrics()

        if enable_server:
            self.start_server()

    def _init_metrics(self) -> None:
        """Initialize Prometheus metrics compatible with go-libp2p format."""
        # Connection metrics - matches go-libp2p format exactly
        self.connections = Gauge(
            "libp2p_rcmgr_connections",
            "Number of connections",
            ["dir", "scope"],
            registry=self.registry,
        )

        # Stream metrics - matches go-libp2p format
        self.streams = Gauge(
            "libp2p_rcmgr_streams",
            "Number of streams",
            ["dir", "scope", "protocol"],
            registry=self.registry,
        )

        # Memory metrics - matches go-libp2p format
        self.memory = Gauge(
            "libp2p_rcmgr_memory",
            "Memory usage as reported to the Resource Manager",
            ["scope", "protocol"],
            registry=self.registry,
        )

        # File descriptor metrics
        self.fds = Gauge(
            "libp2p_rcmgr_fds",
            "File descriptors reserved as reported to the Resource Manager",
            ["scope"],
            registry=self.registry,
        )

        # Blocked resources counter - matches go-libp2p format
        self.blocked_resources = Gauge(
            "libp2p_rcmgr_blocked_resources",
            "Number of blocked resources",
            ["dir", "scope", "resource"],
            registry=self.registry,
        )

        # Peer connection distribution - go-libp2p compatible buckets
        connection_buckets = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16, 32, 64, 128, 256]

        self.peer_connections = Histogram(
            "libp2p_rcmgr_peer_connections",
            "Number of connections this peer has",
            ["dir"],
            buckets=connection_buckets,
            registry=self.registry,
        )

        # Previous peer connections for histogram diff calculation
        self.previous_peer_connections = Histogram(
            "libp2p_rcmgr_previous_peer_connections",
            "Number of connections this peer previously had",
            ["dir"],
            buckets=connection_buckets,
            registry=self.registry,
        )

        # Peer stream distribution
        self.peer_streams = Histogram(
            "libp2p_rcmgr_peer_streams",
            "Number of streams this peer has",
            ["dir"],
            buckets=connection_buckets,  # Same buckets as connections
            registry=self.registry,
        )

        # Previous peer streams for histogram diff calculation
        self.previous_peer_streams = Histogram(
            "libp2p_rcmgr_previous_peer_streams",
            "Number of streams this peer previously had",
            ["dir"],
            buckets=connection_buckets,
            registry=self.registry,
        )

        # Memory distribution buckets (bytes: 1KB to 4GB)
        mem_buckets = [
            1024,  # 1KB
            4096,  # 4KB
            32768,  # 32KB
            1048576,  # 1MB
            33554432,  # 32MB
            268435456,  # 256MB
            536870912,  # 512MB
            1073741824,  # 1GB
            2147483648,  # 2GB
            4294967296,  # 4GB
        ]

        self.peer_memory = Histogram(
            "libp2p_rcmgr_peer_memory",
            "How many peers have reserved this bucket of memory",
            buckets=mem_buckets,
            registry=self.registry,
        )

        self.previous_peer_memory = Histogram(
            "libp2p_rcmgr_previous_peer_memory",
            "How many peers have previously reserved this bucket of memory",
            buckets=mem_buckets,
            registry=self.registry,
        )

        self.conn_memory = Histogram(
            "libp2p_rcmgr_conn_memory",
            "How many connections have reserved this bucket of memory",
            buckets=mem_buckets,
            registry=self.registry,
        )

        self.previous_conn_memory = Histogram(
            "libp2p_rcmgr_previous_conn_memory",
            "How many connections have previously reserved this bucket of memory",
            buckets=mem_buckets,
            registry=self.registry,
        )

    def update_from_metrics(self, metrics: Metrics) -> None:
        """
        Update Prometheus metrics from libp2p Metrics instance.

        Args:
            metrics: The metrics instance to export data from

        """
        with self._lock:
            summary = metrics.get_summary()

            # Update connection metrics
            self.connections.labels(dir="inbound", scope="system").set(
                summary["connections"]["inbound"]
            )
            self.connections.labels(dir="outbound", scope="system").set(
                summary["connections"]["outbound"]
            )

            # Update stream metrics (system scope)
            self.streams.labels(dir="inbound", scope="system", protocol="").set(
                summary["streams"]["inbound"]
            )
            self.streams.labels(dir="outbound", scope="system", protocol="").set(
                summary["streams"]["outbound"]
            )

            # Update memory metrics
            self.memory.labels(scope="system", protocol="").set(
                summary["memory"]["current"]
            )

            # Update file descriptors (estimate based on connections)
            # In a real implementation, you'd track FDs separately
            total_connections = summary["connections"]["total"]
            self.fds.labels(scope="system").set(total_connections)

            # Update blocked resources (convert counters to gauges for compatibility)
            self.blocked_resources.labels(
                dir="", scope="system", resource="connection"
            ).set(summary["blocks"]["connections"])
            self.blocked_resources.labels(
                dir="", scope="system", resource="stream"
            ).set(summary["blocks"]["streams"])
            self.blocked_resources.labels(
                dir="", scope="system", resource="memory"
            ).set(summary["blocks"]["memory"])

    def record_blocked_resource(
        self,
        direction: str,
        scope: str,
        resource: str,
        count: int = 1,
    ) -> None:
        """
        Record a blocked resource event.

        Args:
            direction: Direction of the blocked resource (inbound/outbound)
            scope: Resource scope (system, transient, peer, etc.)
            resource: Type of resource (connection, stream, memory, fd)
            count: Number of resources blocked

        """
        with self._lock:
            current = self.blocked_resources.labels(
                dir=direction, scope=scope, resource=resource
            )._value._value
            self.blocked_resources.labels(
                dir=direction, scope=scope, resource=resource
            ).set(current + count)

    def record_peer_connections(
        self,
        peer_id: str,
        direction: str,
        old_count: int,
        new_count: int,
    ) -> None:
        """
        Record peer connection count for histogram (go-libp2p compatible).

        Args:
            peer_id: Peer identifier
            direction: Connection direction (inbound/outbound)
            old_count: Previous connection count
            new_count: Current connection count

        """
        with self._lock:
            if old_count != new_count:
                if old_count > 0:
                    self.previous_peer_connections.labels(dir=direction).observe(
                        old_count
                    )
                if new_count > 0:
                    self.peer_connections.labels(dir=direction).observe(new_count)

            # Update tracking
            if peer_id not in self._peer_connections:
                self._peer_connections[peer_id] = {"inbound": 0, "outbound": 0}
            self._peer_connections[peer_id][direction] = new_count

    def record_peer_streams(
        self,
        peer_id: str,
        direction: str,
        old_count: int,
        new_count: int,
    ) -> None:
        """
        Record peer stream count for histogram (go-libp2p compatible).

        Args:
            peer_id: Peer identifier
            direction: Stream direction (inbound/outbound)
            old_count: Previous stream count
            new_count: Current stream count

        """
        with self._lock:
            if old_count != new_count:
                if old_count > 0:
                    self.previous_peer_streams.labels(dir=direction).observe(old_count)
                if new_count > 0:
                    self.peer_streams.labels(dir=direction).observe(new_count)

            # Update tracking
            if peer_id not in self._peer_streams:
                self._peer_streams[peer_id] = {"inbound": 0, "outbound": 0}
            self._peer_streams[peer_id][direction] = new_count

    def record_peer_memory(self, peer_id: str, old_bytes: int, new_bytes: int) -> None:
        """
        Record peer memory usage for histogram.

        Args:
            peer_id: Peer identifier
            old_bytes: Previous memory usage in bytes
            new_bytes: Current memory usage in bytes

        """
        with self._lock:
            if old_bytes != new_bytes:
                if old_bytes > 0:
                    self.previous_peer_memory.observe(old_bytes)
                if new_bytes > 0:
                    self.peer_memory.observe(new_bytes)

            self._peer_memory[peer_id] = new_bytes

    def record_conn_memory(self, conn_id: str, old_bytes: int, new_bytes: int) -> None:
        """
        Record connection memory usage for histogram.

        Args:
            conn_id: Connection identifier
            old_bytes: Previous memory usage in bytes
            new_bytes: Current memory usage in bytes

        """
        with self._lock:
            if old_bytes != new_bytes:
                if old_bytes > 0:
                    self.previous_conn_memory.observe(old_bytes)
                if new_bytes > 0:
                    self.conn_memory.observe(new_bytes)

            self._conn_memory[conn_id] = new_bytes

    def start_server(self) -> None:
        """Start the Prometheus metrics HTTP server."""
        if self._running or not self.enable_server:
            return

        self._running = True
        self._server_thread = threading.Thread(
            target=self._run_server, daemon=True, name="PrometheusMetricsServer"
        )
        self._server_thread.start()

    def _run_server(self) -> None:
        """Run the Prometheus HTTP server."""
        try:
            start_http_server(self.port, registry=self.registry)
        except Exception as e:
            print(f"Failed to start Prometheus metrics server on port {self.port}: {e}")
            self._running = False

    def stop_server(self) -> None:
        """Stop the Prometheus metrics server."""
        self._running = False

    def get_metrics_text(self) -> str:
        """
        Get metrics in Prometheus text format.

        Returns:
            Metrics in Prometheus exposition format

        """
        return generate_latest(self.registry).decode("utf-8")

    def get_metrics_content_type(self) -> str:
        """
        Get the content type for Prometheus metrics.

        Returns:
            Content type string

        """
        return CONTENT_TYPE_LATEST

    def reset(self) -> None:
        """Reset all tracking data."""
        with self._lock:
            self._peer_connections.clear()
            self._peer_streams.clear()
            self._peer_memory.clear()
            self._conn_memory.clear()


def create_prometheus_exporter(
    port: int = 8000,
    enable_server: bool = True,
) -> PrometheusExporter | None:
    """
    Create a PrometheusExporter instance if prometheus_client is available.

    Args:
        port: HTTP port for metrics endpoint
        enable_server: Whether to start the HTTP server automatically

    Returns:
        PrometheusExporter instance or None if prometheus_client not available

    """
    if not PROMETHEUS_AVAILABLE:
        print(
            "Warning: prometheus_client not available. "
            "Install with: pip install prometheus-client"
        )
        return None

    try:
        return PrometheusExporter(port=port, enable_server=enable_server)
    except Exception as e:
        print(f"Failed to create Prometheus exporter: {e}")
        return None

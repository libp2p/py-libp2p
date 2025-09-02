"""
Configuration classes for QUIC transport.
"""

from dataclasses import (
    dataclass,
    field,
)
import ssl
from typing import Any, Literal, TypedDict

from libp2p.custom_types import TProtocol
from libp2p.network.config import ConnectionConfig


class QUICTransportKwargs(TypedDict, total=False):
    """Type definition for kwargs accepted by new_transport function."""

    # Connection settings
    idle_timeout: float
    max_datagram_size: int
    local_port: int | None

    # Protocol version support
    enable_draft29: bool
    enable_v1: bool

    # TLS settings
    verify_mode: ssl.VerifyMode
    alpn_protocols: list[str]

    # Performance settings
    max_concurrent_streams: int
    connection_window: int
    stream_window: int

    # Logging and debugging
    enable_qlog: bool
    qlog_dir: str | None

    # Connection management
    max_connections: int
    connection_timeout: float

    # Protocol identifiers
    PROTOCOL_QUIC_V1: TProtocol
    PROTOCOL_QUIC_DRAFT29: TProtocol


@dataclass
class QUICTransportConfig(ConnectionConfig):
    """Configuration for QUIC transport."""

    # Connection settings
    idle_timeout: float = 30.0  # Seconds before an idle connection is closed.
    max_datagram_size: int = (
        1200  # Maximum size of UDP datagrams to avoid IP fragmentation.
    )
    local_port: int | None = (
        None  # Local port to bind to. If None, a random port is chosen.
    )

    # Protocol version support
    enable_draft29: bool = True  # Enable QUIC draft-29 for compatibility
    enable_v1: bool = True  # Enable QUIC v1 (RFC 9000)

    # TLS settings
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE
    alpn_protocols: list[str] = field(default_factory=lambda: ["libp2p"])

    # Performance settings
    max_concurrent_streams: int = 100  # Maximum concurrent streams per connection
    connection_window: int = 1024 * 1024  # Connection flow control window
    stream_window: int = 64 * 1024  # Stream flow control window

    # Logging and debugging
    enable_qlog: bool = False  # Enable QUIC logging
    qlog_dir: str | None = None  # Directory for QUIC logs

    # Connection management
    max_connections: int = 1000  # Maximum number of connections
    connection_timeout: float = 10.0  # Connection establishment timeout

    MAX_CONCURRENT_STREAMS: int = 1000
    """Maximum number of concurrent streams per connection."""

    MAX_INCOMING_STREAMS: int = 1000
    """Maximum number of incoming streams per connection."""

    CONNECTION_HANDSHAKE_TIMEOUT: float = 60.0
    """Timeout for connection handshake (seconds)."""

    MAX_OUTGOING_STREAMS: int = 1000
    """Maximum number of outgoing streams per connection."""

    CONNECTION_CLOSE_TIMEOUT: int = 10
    """Timeout for opening new connection (seconds)."""

    # Stream timeouts
    STREAM_OPEN_TIMEOUT: float = 5.0
    """Timeout for opening new streams (seconds)."""

    STREAM_ACCEPT_TIMEOUT: float = 30.0
    """Timeout for accepting incoming streams (seconds)."""

    STREAM_READ_TIMEOUT: float = 30.0
    """Default timeout for stream read operations (seconds)."""

    STREAM_WRITE_TIMEOUT: float = 30.0
    """Default timeout for stream write operations (seconds)."""

    STREAM_CLOSE_TIMEOUT: float = 10.0
    """Timeout for graceful stream close (seconds)."""

    # Flow control configuration
    STREAM_FLOW_CONTROL_WINDOW: int = 1024 * 1024  # 1MB
    """Per-stream flow control window size."""

    CONNECTION_FLOW_CONTROL_WINDOW: int = 1536 * 1024  # 1.5MB
    """Connection-wide flow control window size."""

    # Buffer management
    MAX_STREAM_RECEIVE_BUFFER: int = 2 * 1024 * 1024  # 2MB
    """Maximum receive buffer size per stream."""

    STREAM_RECEIVE_BUFFER_LOW_WATERMARK: int = 64 * 1024  # 64KB
    """Low watermark for stream receive buffer."""

    STREAM_RECEIVE_BUFFER_HIGH_WATERMARK: int = 512 * 1024  # 512KB
    """High watermark for stream receive buffer."""

    # Stream lifecycle configuration
    ENABLE_STREAM_RESET_ON_ERROR: bool = True
    """Whether to automatically reset streams on errors."""

    STREAM_RESET_ERROR_CODE: int = 1
    """Default error code for stream resets."""

    ENABLE_STREAM_KEEP_ALIVE: bool = False
    """Whether to enable stream keep-alive mechanisms."""

    STREAM_KEEP_ALIVE_INTERVAL: float = 30.0
    """Interval for stream keep-alive pings (seconds)."""

    # Resource management
    ENABLE_STREAM_RESOURCE_TRACKING: bool = True
    """Whether to track stream resource usage."""

    STREAM_MEMORY_LIMIT_PER_STREAM: int = 2 * 1024 * 1024  # 2MB
    """Memory limit per individual stream."""

    STREAM_MEMORY_LIMIT_PER_CONNECTION: int = 100 * 1024 * 1024  # 100MB
    """Total memory limit for all streams per connection."""

    # Concurrency and performance
    ENABLE_STREAM_BATCHING: bool = True
    """Whether to batch multiple stream operations."""

    STREAM_BATCH_SIZE: int = 10
    """Number of streams to process in a batch."""

    STREAM_PROCESSING_CONCURRENCY: int = 100
    """Maximum concurrent stream processing tasks."""

    # Debugging and monitoring
    ENABLE_STREAM_METRICS: bool = True
    """Whether to collect stream metrics."""

    ENABLE_STREAM_TIMELINE_TRACKING: bool = True
    """Whether to track stream lifecycle timelines."""

    STREAM_METRICS_COLLECTION_INTERVAL: float = 60.0
    """Interval for collecting stream metrics (seconds)."""

    # Error handling configuration
    STREAM_ERROR_RETRY_ATTEMPTS: int = 3
    """Number of retry attempts for recoverable stream errors."""

    STREAM_ERROR_RETRY_DELAY: float = 1.0
    """Initial delay between stream error retries (seconds)."""

    STREAM_ERROR_RETRY_BACKOFF_FACTOR: float = 2.0
    """Backoff factor for stream error retries."""

    # Protocol identifiers matching go-libp2p
    PROTOCOL_QUIC_V1: TProtocol = TProtocol("quic-v1")  # RFC 9000
    PROTOCOL_QUIC_DRAFT29: TProtocol = TProtocol("quic")  # draft-29

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not (self.enable_draft29 or self.enable_v1):
            raise ValueError("At least one QUIC version must be enabled")

        if self.idle_timeout <= 0:
            raise ValueError("Idle timeout must be positive")

        if self.max_datagram_size < 1200:
            raise ValueError("Max datagram size must be at least 1200 bytes")

        # Validate timeouts
        timeout_fields = [
            "STREAM_OPEN_TIMEOUT",
            "STREAM_ACCEPT_TIMEOUT",
            "STREAM_READ_TIMEOUT",
            "STREAM_WRITE_TIMEOUT",
            "STREAM_CLOSE_TIMEOUT",
        ]
        for timeout_field in timeout_fields:
            if getattr(self, timeout_field) <= 0:
                raise ValueError(f"{timeout_field} must be positive")

        # Validate flow control windows
        if self.STREAM_FLOW_CONTROL_WINDOW <= 0:
            raise ValueError("STREAM_FLOW_CONTROL_WINDOW must be positive")

        if self.CONNECTION_FLOW_CONTROL_WINDOW < self.STREAM_FLOW_CONTROL_WINDOW:
            raise ValueError(
                "CONNECTION_FLOW_CONTROL_WINDOW must be >= STREAM_FLOW_CONTROL_WINDOW"
            )

        # Validate buffer sizes
        if self.MAX_STREAM_RECEIVE_BUFFER <= 0:
            raise ValueError("MAX_STREAM_RECEIVE_BUFFER must be positive")

        if self.STREAM_RECEIVE_BUFFER_HIGH_WATERMARK > self.MAX_STREAM_RECEIVE_BUFFER:
            raise ValueError(
                "STREAM_RECEIVE_BUFFER_HIGH_WATERMARK cannot".__add__(
                    "exceed MAX_STREAM_RECEIVE_BUFFER"
                )
            )

        if (
            self.STREAM_RECEIVE_BUFFER_LOW_WATERMARK
            >= self.STREAM_RECEIVE_BUFFER_HIGH_WATERMARK
        ):
            raise ValueError(
                "STREAM_RECEIVE_BUFFER_LOW_WATERMARK must be < HIGH_WATERMARK"
            )

        # Validate memory limits
        if self.STREAM_MEMORY_LIMIT_PER_STREAM <= 0:
            raise ValueError("STREAM_MEMORY_LIMIT_PER_STREAM must be positive")

        if self.STREAM_MEMORY_LIMIT_PER_CONNECTION <= 0:
            raise ValueError("STREAM_MEMORY_LIMIT_PER_CONNECTION must be positive")

        expected_stream_memory = (
            self.MAX_CONCURRENT_STREAMS * self.STREAM_MEMORY_LIMIT_PER_STREAM
        )
        if expected_stream_memory > self.STREAM_MEMORY_LIMIT_PER_CONNECTION * 2:
            # Allow some headroom, but warn if configuration seems inconsistent
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                "Stream memory configuration may be inconsistent: "
                f"{self.MAX_CONCURRENT_STREAMS} streams ×"
                "{self.STREAM_MEMORY_LIMIT_PER_STREAM} bytes "
                "could exceed connection limit of"
                f"{self.STREAM_MEMORY_LIMIT_PER_CONNECTION} bytes"
            )

    def get_stream_config_dict(self) -> dict[str, Any]:
        """Get stream-specific configuration as dictionary."""
        stream_config = {}
        for attr_name in dir(self):
            if attr_name.startswith(
                ("STREAM_", "MAX_", "ENABLE_STREAM", "CONNECTION_FLOW")
            ):
                stream_config[attr_name.lower()] = getattr(self, attr_name)
        return stream_config


# Additional configuration classes for specific stream features


class QUICStreamFlowControlConfig:
    """Configuration for QUIC stream flow control."""

    def __init__(
        self,
        initial_window_size: int = 512 * 1024,
        max_window_size: int = 2 * 1024 * 1024,
        window_update_threshold: float = 0.5,
        enable_auto_tuning: bool = True,
    ):
        self.initial_window_size = initial_window_size
        self.max_window_size = max_window_size
        self.window_update_threshold = window_update_threshold
        self.enable_auto_tuning = enable_auto_tuning


def create_stream_config_for_use_case(
    use_case: Literal[
        "high_throughput", "low_latency", "many_streams", "memory_constrained"
    ],
) -> QUICTransportConfig:
    """
    Create optimized stream configuration for specific use cases.

    Args:
        use_case: One of "high_throughput", "low_latency", "many_streams","
                  "memory_constrained"

    Returns:
        Optimized QUICTransportConfig

    """
    base_config = QUICTransportConfig()

    if use_case == "high_throughput":
        # Optimize for high throughput
        base_config.STREAM_FLOW_CONTROL_WINDOW = 2 * 1024 * 1024  # 2MB
        base_config.CONNECTION_FLOW_CONTROL_WINDOW = 10 * 1024 * 1024  # 10MB
        base_config.MAX_STREAM_RECEIVE_BUFFER = 4 * 1024 * 1024  # 4MB
        base_config.STREAM_PROCESSING_CONCURRENCY = 200

    elif use_case == "low_latency":
        # Optimize for low latency
        base_config.STREAM_OPEN_TIMEOUT = 1.0
        base_config.STREAM_READ_TIMEOUT = 5.0
        base_config.STREAM_WRITE_TIMEOUT = 5.0
        base_config.ENABLE_STREAM_BATCHING = False
        base_config.STREAM_BATCH_SIZE = 1

    elif use_case == "many_streams":
        # Optimize for many concurrent streams
        base_config.MAX_CONCURRENT_STREAMS = 5000
        base_config.STREAM_FLOW_CONTROL_WINDOW = 128 * 1024  # 128KB
        base_config.MAX_STREAM_RECEIVE_BUFFER = 256 * 1024  # 256KB
        base_config.STREAM_PROCESSING_CONCURRENCY = 500

    elif use_case == "memory_constrained":
        # Optimize for low memory usage
        base_config.MAX_CONCURRENT_STREAMS = 100
        base_config.STREAM_FLOW_CONTROL_WINDOW = 64 * 1024  # 64KB
        base_config.CONNECTION_FLOW_CONTROL_WINDOW = 256 * 1024  # 256KB
        base_config.MAX_STREAM_RECEIVE_BUFFER = 128 * 1024  # 128KB
        base_config.STREAM_MEMORY_LIMIT_PER_STREAM = 512 * 1024  # 512KB
        base_config.STREAM_PROCESSING_CONCURRENCY = 50

    else:
        raise ValueError(f"Unknown use case: {use_case}")

    return base_config

"""
Configuration classes for QUIC transport.
"""

from dataclasses import (
    dataclass,
    field,
)
import ssl
from typing import TypedDict

from libp2p.custom_types import TProtocol


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
class QUICTransportConfig:
    """Configuration for QUIC transport."""

    # Connection settings
    idle_timeout: float = 30.0  # Connection idle timeout in seconds
    max_datagram_size: int = 1200  # Maximum UDP datagram size
    local_port: int | None = None  # Local port for binding (None = random)

    # Protocol version support
    enable_draft29: bool = True  # Enable QUIC draft-29 for compatibility
    enable_v1: bool = True  # Enable QUIC v1 (RFC 9000)

    # TLS settings
    verify_mode: ssl.VerifyMode = ssl.CERT_REQUIRED
    alpn_protocols: list[str] = field(default_factory=lambda: ["libp2p"])

    # Performance settings
    max_concurrent_streams: int = 1000  # Maximum concurrent streams per connection
    connection_window: int = 1024 * 1024  # Connection flow control window
    stream_window: int = 64 * 1024  # Stream flow control window

    # Logging and debugging
    enable_qlog: bool = False  # Enable QUIC logging
    qlog_dir: str | None = None  # Directory for QUIC logs

    # Connection management
    max_connections: int = 1000  # Maximum number of connections
    connection_timeout: float = 10.0  # Connection establishment timeout

    # Protocol identifiers matching go-libp2p
    # TODO: UNTIL MUITIADDR REPO IS UPDATED
    # PROTOCOL_QUIC_V1: TProtocol = TProtocol("/quic-v1")  # RFC 9000
    PROTOCOL_QUIC_V1: TProtocol = TProtocol("quic")  # RFC 9000
    PROTOCOL_QUIC_DRAFT29: TProtocol = TProtocol("quic")  # draft-29

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not (self.enable_draft29 or self.enable_v1):
            raise ValueError("At least one QUIC version must be enabled")

        if self.idle_timeout <= 0:
            raise ValueError("Idle timeout must be positive")

        if self.max_datagram_size < 1200:
            raise ValueError("Max datagram size must be at least 1200 bytes")

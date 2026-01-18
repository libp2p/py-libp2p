"""
Configuration constants matching go-libp2p connection manager defaults.

Reference: https://pkg.go.dev/github.com/libp2p/go-libp2p/p2p/net/connmgr
"""

from dataclasses import (
    dataclass,
    field,
)

# Default connection limits (matching go-libp2p)
MAX_CONNECTIONS = 300
MIN_CONNECTIONS = 50  # Minimum connections to maintain (go-libp2p default)
LOW_WATERMARK = 100  # Start auto-connecting when below this (go-libp2p default)
HIGH_WATERMARK = 200  # Start pruning when above this (go-libp2p default)
MAX_PEER_ADDRS_TO_DIAL = 25

# Default timeout values (in seconds)
DIAL_TIMEOUT = 10.0  # 10_000ms
CONNECTION_CLOSE_TIMEOUT = 1.0  # 1_000ms
INBOUND_UPGRADE_TIMEOUT = 10.0  # 10_000ms
OUTBOUND_UPGRADE_TIMEOUT = 10.0  # 10_000ms
OUTBOUND_STREAM_PROTOCOL_NEGOTIATION_TIMEOUT = 10.0  # 10_000ms
INBOUND_STREAM_PROTOCOL_NEGOTIATION_TIMEOUT = 10.0  # 10_000ms

# Auto-connection settings
AUTO_CONNECT_INTERVAL = 30.0  # Interval in seconds between auto-connect attempts
GRACE_PERIOD = 20.0  # Grace period in seconds before pruning new connections


@dataclass
class RetryConfig:
    """
    Configuration for retry logic with exponential backoff.

    This configuration controls how connection attempts are retried when they fail.
    The retry mechanism uses exponential backoff with jitter to prevent thundering
    herd problems in distributed systems.

    Attributes:
        max_retries: Maximum number of retry attempts before giving up.
                     Default: 3 attempts
        initial_delay: Initial delay in seconds before the first retry.
                      Default: 0.1 seconds (100ms)
        max_delay: Maximum delay cap in seconds to prevent excessive wait times.
                  Default: 30.0 seconds
        backoff_multiplier: Multiplier for exponential backoff (each retry multiplies
                           the delay by this factor). Default: 2.0 (doubles each time)
        jitter_factor: Random jitter factor (0.0-1.0) to add randomness to delays
                      and prevent synchronized retries. Default: 0.1 (10% jitter)

    """

    max_retries: int = 3
    initial_delay: float = 0.1
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1


@dataclass
class ConnectionConfig:
    """
    Configuration for connection management matching go-libp2p ConnManager.

    This configuration controls connection limits, timeouts, and watermarks
    for libp2p connections using go-libp2p style connection management.

    Attributes:
        max_connections: Maximum total connections (inbound + outbound).
                         Default: 300
        min_connections: Minimum connections to maintain. The connection manager
                        will try to keep at least this many connections open.
                        Default: 50
        low_watermark: When connection count falls below this, auto-connect to
                      known peers. Default: 100
        high_watermark: When connection count exceeds this, start pruning
                       connections. Default: 200
        max_connections_per_peer: Maximum number of connections allowed to a single
                                 peer. Default: 3 connections
        max_peer_addrs_to_dial: Maximum addresses to attempt per peer. Default: 25
        dial_timeout: Timeout in seconds for establishing dial connections.
                     Default: 10.0
        connection_close_timeout: Timeout in seconds for closing connections.
                                 Default: 1.0
        inbound_upgrade_timeout: Timeout in seconds for inbound connection upgrades.
                                Default: 10.0
        outbound_upgrade_timeout: Timeout in seconds for outbound connection upgrades
                                 (security and muxer negotiation). Default: 10.0
        outbound_stream_protocol_negotiation_timeout: Timeout in seconds for
            outbound stream protocol negotiation. Default: 10.0
        inbound_stream_protocol_negotiation_timeout: Timeout in seconds for
            inbound stream protocol negotiation. Default: 10.0
        connection_timeout: Legacy timeout - use dial_timeout instead.
                           Default: 30.0 (kept for backward compatibility)
        load_balancing_strategy: Strategy for distributing streams across connections.
                                Options: "round_robin" (default) or "least_loaded"
        auto_connect_interval: Interval between auto-connect attempts when below
                              low_watermark. Default: 30.0 seconds
        grace_period: Time to wait before pruning a new connection.
                     Default: 20.0 seconds
        allow_list: List of IP addresses/networks (CIDR) that are always allowed
                   to connect (ConnectionGater allow list).
        deny_list: List of IP addresses/networks (CIDR) that are never allowed
                  to connect (ConnectionGater deny list).

    """

    # Global connection limits (go-libp2p style)
    max_connections: int = MAX_CONNECTIONS
    min_connections: int = MIN_CONNECTIONS
    low_watermark: int = LOW_WATERMARK
    high_watermark: int = HIGH_WATERMARK
    max_peer_addrs_to_dial: int = MAX_PEER_ADDRS_TO_DIAL

    # Per-peer limits
    max_connections_per_peer: int = 3

    # Timeout configuration
    dial_timeout: float = DIAL_TIMEOUT
    connection_close_timeout: float = CONNECTION_CLOSE_TIMEOUT
    inbound_upgrade_timeout: float = INBOUND_UPGRADE_TIMEOUT
    outbound_upgrade_timeout: float = OUTBOUND_UPGRADE_TIMEOUT
    outbound_stream_protocol_negotiation_timeout: float = (
        OUTBOUND_STREAM_PROTOCOL_NEGOTIATION_TIMEOUT
    )
    inbound_stream_protocol_negotiation_timeout: float = (
        INBOUND_STREAM_PROTOCOL_NEGOTIATION_TIMEOUT
    )
    # Legacy timeout - kept for backward compatibility
    connection_timeout: float = 30.0

    # Load balancing
    load_balancing_strategy: str = "round_robin"  # or "least_loaded"

    # Auto-connection configuration
    auto_connect_interval: float = AUTO_CONNECT_INTERVAL
    grace_period: float = GRACE_PERIOD

    # Connection gating (go-libp2p ConnectionGater)
    allow_list: list[str] = field(default_factory=list)
    deny_list: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not (
            self.load_balancing_strategy == "round_robin"
            or self.load_balancing_strategy == "least_loaded"
        ):
            raise ValueError(
                "Load balancing strategy can only be 'round_robin' or 'least_loaded'"
            )

        if self.max_connections_per_peer < 1:
            raise ValueError("Max connection per peer should be at least 1")

        if self.max_connections < 1:
            raise ValueError("Max connections should be at least 1")

        if self.min_connections < 0:
            raise ValueError("Min connections should be non-negative")

        if self.low_watermark < self.min_connections:
            raise ValueError("Low watermark should be >= min_connections")

        if self.high_watermark < self.low_watermark:
            raise ValueError("High watermark should be >= low_watermark")

        if self.max_connections < self.high_watermark:
            raise ValueError("Max connections should be >= high_watermark")

        if self.dial_timeout < 0:
            raise ValueError("Dial timeout should be positive")

        if self.inbound_upgrade_timeout < 0:
            raise ValueError("Inbound upgrade timeout should be positive")

        if self.outbound_upgrade_timeout < 0:
            raise ValueError("Outbound upgrade timeout should be positive")

        if self.connection_timeout < 0:
            raise ValueError("Connection timeout should be positive")

        if self.auto_connect_interval <= 0:
            raise ValueError("Auto connect interval should be positive")

        if self.grace_period < 0:
            raise ValueError("Grace period should be non-negative")

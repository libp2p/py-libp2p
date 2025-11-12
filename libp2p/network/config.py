"""
Configuration constants matching JavaScript libp2p connection manager defaults.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/constants.ts
"""

from collections.abc import (
    Callable,
)
from dataclasses import (
    dataclass,
    field,
)
from typing import Any

# Default connection limits (matching JS libp2p)
MAX_CONNECTIONS = 300
MAX_PARALLEL_DIALS = 100
MAX_DIAL_QUEUE_LENGTH = 500
MAX_PEER_ADDRS_TO_DIAL = 25
MAX_INCOMING_PENDING_CONNECTIONS = 10

# Default timeout values (in seconds, matching JS libp2p defaults in ms / 1000)
DIAL_TIMEOUT = 10.0  # 10_000ms
CONNECTION_CLOSE_TIMEOUT = 1.0  # 1_000ms
INBOUND_UPGRADE_TIMEOUT = 10.0  # 10_000ms
OUTBOUND_STREAM_PROTOCOL_NEGOTIATION_TIMEOUT = 10.0  # 10_000ms
INBOUND_STREAM_PROTOCOL_NEGOTIATION_TIMEOUT = 10.0  # 10_000ms

# Default reconnection settings
RECONNECT_RETRIES = 5
RECONNECT_RETRY_INTERVAL = 1.0  # 1_000ms
RECONNECT_BACKOFF_FACTOR = 2.0
MAX_PARALLEL_RECONNECTS = 5

# Default rate limiting
INBOUND_CONNECTION_THRESHOLD = 5  # connections per second

# Default dial priority
DEFAULT_DIAL_PRIORITY = 50


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
    Configuration for connection management matching JS libp2p behavior.

    This configuration controls connection limits, timeouts, rate limiting,
    security, and queue management for libp2p connections.

    Attributes:
        max_connections: Maximum total connections (inbound + outbound).
                         Default: 300
        max_connections_per_peer: Maximum number of connections allowed to a single
                                 peer. Default: 3 connections
        max_parallel_dials: Maximum concurrent dial attempts. Default: 100
        max_dial_queue_length: Maximum dial queue size. Default: 500
        max_peer_addrs_to_dial: Maximum addresses to attempt per peer. Default: 25
        max_incoming_pending_connections: Maximum pending inbound connections.
                                         Default: 10
        dial_timeout: Timeout in seconds for establishing dial connections
                     (including DNS resolution). Default: 10.0
        connection_close_timeout: Timeout in seconds for closing connections.
                                 Default: 1.0
        inbound_upgrade_timeout: Timeout in seconds for inbound connection upgrades.
                                Default: 10.0
        outbound_stream_protocol_negotiation_timeout: Timeout in seconds for
            outbound stream protocol negotiation. Default: 10.0
        inbound_stream_protocol_negotiation_timeout: Timeout in seconds for
            inbound stream protocol negotiation. Default: 10.0
        connection_timeout: Legacy timeout - use dial_timeout instead.
                           Default: 30.0 (kept for backward compatibility)
        load_balancing_strategy: Strategy for distributing streams across connections.
                                Options: "round_robin" (default) or "least_loaded"
        inbound_connection_threshold: Maximum connections per second from a single
                                      host. Default: 5
        reconnect_retries: Number of reconnection attempts for KEEP_ALIVE peers.
                         Default: 5
        reconnect_retry_interval: Initial delay in seconds between reconnection
                                  attempts. Default: 1.0
        reconnect_backoff_factor: Exponential backoff factor for reconnections.
                                 Default: 2.0
        max_parallel_reconnects: Maximum concurrent reconnection attempts.
                               Default: 5
        allow_list: List of IP addresses/networks (CIDR) that are always allowed
                   to connect, even if max_connections is reached.
        deny_list: List of IP addresses/networks (CIDR) that are never allowed
                  to connect.
        address_sorter: Optional function to sort addresses before dialing.
                       If None, uses default sorting strategy.

    """

    # Global connection limits
    max_connections: int = MAX_CONNECTIONS
    max_parallel_dials: int = MAX_PARALLEL_DIALS
    max_dial_queue_length: int = MAX_DIAL_QUEUE_LENGTH
    max_peer_addrs_to_dial: int = MAX_PEER_ADDRS_TO_DIAL
    max_incoming_pending_connections: int = MAX_INCOMING_PENDING_CONNECTIONS

    # Per-peer limits
    max_connections_per_peer: int = 3

    # Timeout configuration
    dial_timeout: float = DIAL_TIMEOUT
    connection_close_timeout: float = CONNECTION_CLOSE_TIMEOUT
    inbound_upgrade_timeout: float = INBOUND_UPGRADE_TIMEOUT
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

    # Rate limiting
    inbound_connection_threshold: int = INBOUND_CONNECTION_THRESHOLD

    # Reconnection configuration
    reconnect_retries: int = RECONNECT_RETRIES
    reconnect_retry_interval: float = RECONNECT_RETRY_INTERVAL
    reconnect_backoff_factor: float = RECONNECT_BACKOFF_FACTOR
    max_parallel_reconnects: int = MAX_PARALLEL_RECONNECTS

    # Security/access control
    allow_list: list[str] = field(default_factory=list)
    deny_list: list[str] = field(default_factory=list)

    # Address management
    address_sorter: Callable[..., Any] | None = None

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

        if self.max_parallel_dials < 1:
            raise ValueError("Max parallel dials should be at least 1")

        if self.dial_timeout < 0:
            raise ValueError("Dial timeout should be positive")

        if self.connection_timeout < 0:
            raise ValueError("Connection timeout should be positive")

        if self.reconnect_backoff_factor <= 0:
            raise ValueError("Reconnect backoff factor should be positive")

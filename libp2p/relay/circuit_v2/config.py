"""
Configuration management for Circuit Relay v2.

This module handles configuration for relay roles, resource limits,
and discovery settings.
"""

from dataclasses import (
    dataclass,
    field,
)

from enum import Flag, auto

from libp2p.peer.peerinfo import (
    PeerInfo,
)

from .resources import (
    RelayLimits,
)

DEFAULT_MIN_RELAYS = 3
DEFAULT_MAX_RELAYS = 20
DEFAULT_DISCOVERY_INTERVAL = 300  # seconds
DEFAULT_RESERVATION_TTL = 3600  # seconds
DEFAULT_MAX_CIRCUIT_DURATION = 3600  # seconds
DEFAULT_MAX_CIRCUIT_BYTES = 1024 * 1024 * 1024  # 1GB

DEFAULT_MAX_CIRCUIT_CONNS = 8
DEFAULT_MAX_RESERVATIONS = 4

MAX_RESERVATIONS_PER_IP = 8
MAX_CIRCUITS_PER_IP = 16
RESERVATION_RATE_PER_IP = 4  # per minute
CIRCUIT_RATE_PER_IP = 8  # per minute
MAX_CIRCUITS_TOTAL = 64
MAX_RESERVATIONS_TOTAL = 32
MAX_BANDWIDTH_PER_CIRCUIT = 1024 * 1024  # 1MB/s
MAX_BANDWIDTH_TOTAL = 10 * 1024 * 1024  # 10MB/s

MIN_RELAY_SCORE = 0.5
MAX_RELAY_LATENCY = 1.0  # seconds
ENABLE_AUTO_RELAY = True
AUTO_RELAY_TIMEOUT = 30  # seconds
MAX_AUTO_RELAY_ATTEMPTS = 3
RESERVATION_REFRESH_THRESHOLD = 0.8  # Refresh at 80% of TTL
MAX_CONCURRENT_RESERVATIONS = 2

# Shared timeout constants (used across modules)
STREAM_READ_TIMEOUT = 15  # seconds
STREAM_WRITE_TIMEOUT = 15  # seconds
STREAM_CLOSE_TIMEOUT = 10  # seconds
DIAL_TIMEOUT = 10  # seconds

# NAT reachability timeout
REACHABILITY_TIMEOUT = 10  # seconds

# Relay roles enum -----------------------------------------------------------


class RelayRole(Flag):
    """Bit-flag enum that captures the three possible relay capabilities.

    A node can combine multiple roles via bit-wise OR, e.g. ``RelayRole.HOP | RelayRole.STOP``.
    """

    HOP = auto()  # Act as a relay for others ("hop")
    STOP = auto()  # Accept relayed connections ("stop")
    CLIENT = auto()  # Dial through existing relays ("client")


class RelayConfig:
    """Configuration for Circuit Relay v2."""

    # Role configuration (bit-flags)
    roles: RelayRole = RelayRole.STOP | RelayRole.CLIENT

    # Resource limits
    limits: RelayLimits | None = None

    # Discovery configuration
    bootstrap_relays: list[PeerInfo] = field(default_factory=list)
    min_relays: int = DEFAULT_MIN_RELAYS
    max_relays: int = DEFAULT_MAX_RELAYS
    discovery_interval: int = DEFAULT_DISCOVERY_INTERVAL

    # Connection configuration
    reservation_ttl: int = DEFAULT_RESERVATION_TTL
    max_circuit_duration: int = DEFAULT_MAX_CIRCUIT_DURATION
    max_circuit_bytes: int = DEFAULT_MAX_CIRCUIT_BYTES

    # ---------------------------------------------------------------------
    # Backwards-compat boolean helpers.  Existing code that still accesses
    # ``cfg.enable_hop, cfg.enable_stop, cfg.enable_client`` will continue to work.
    # ---------------------------------------------------------------------

    @property
    def enable_hop(self) -> bool:  # pragma: no cover – helper
        return bool(self.roles & RelayRole.HOP)

    @property
    def enable_stop(self) -> bool:  # pragma: no cover – helper
        return bool(self.roles & RelayRole.STOP)

    @property
    def enable_client(self) -> bool:  # pragma: no cover – helper
        return bool(self.roles & RelayRole.CLIENT)

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.limits is None:
            self.limits = RelayLimits(
                duration=self.max_circuit_duration,
                data=self.max_circuit_bytes,
                max_circuit_conns=DEFAULT_MAX_CIRCUIT_CONNS,
                max_reservations=DEFAULT_MAX_RESERVATIONS,
            )


@dataclass
class HopConfig:
    """Configuration specific to relay (hop) nodes."""

    # Resource limits per IP
    max_reservations_per_ip: int = MAX_RESERVATIONS_PER_IP
    max_circuits_per_ip: int = MAX_CIRCUITS_PER_IP

    # Rate limiting
    reservation_rate_per_ip: int = RESERVATION_RATE_PER_IP
    circuit_rate_per_ip: int = CIRCUIT_RATE_PER_IP

    # Resource quotas
    max_circuits_total: int = MAX_CIRCUITS_TOTAL
    max_reservations_total: int = MAX_RESERVATIONS_TOTAL

    # Bandwidth limits
    max_bandwidth_per_circuit: int = MAX_BANDWIDTH_PER_CIRCUIT
    max_bandwidth_total: int = MAX_BANDWIDTH_TOTAL


@dataclass
class ClientConfig:
    """Configuration specific to relay clients."""

    # Relay selection
    min_relay_score: float = MIN_RELAY_SCORE
    max_relay_latency: float = MAX_RELAY_LATENCY

    # Auto-relay settings
    enable_auto_relay: bool = ENABLE_AUTO_RELAY
    auto_relay_timeout: int = AUTO_RELAY_TIMEOUT
    max_auto_relay_attempts: int = MAX_AUTO_RELAY_ATTEMPTS

    # Reservation management
    reservation_refresh_threshold: float = RESERVATION_REFRESH_THRESHOLD
    max_concurrent_reservations: int = MAX_CONCURRENT_RESERVATIONS

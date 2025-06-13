"""
Configuration management for Circuit Relay v2.

This module handles configuration for relay roles, resource limits,
and discovery settings.
"""

from dataclasses import (
    dataclass,
    field,
)

from libp2p.peer.peerinfo import (
    PeerInfo,
)

from .resources import (
    RelayLimits,
)


@dataclass
class RelayConfig:
    """Configuration for Circuit Relay v2."""

    # Role configuration
    enable_hop: bool = False  # Whether to act as a relay (hop)
    enable_stop: bool = True  # Whether to accept relayed connections (stop)
    enable_client: bool = True  # Whether to use relays for dialing

    # Resource limits
    limits: RelayLimits | None = None

    # Discovery configuration
    bootstrap_relays: list[PeerInfo] = field(default_factory=list)
    min_relays: int = 3
    max_relays: int = 20
    discovery_interval: int = 300  # seconds

    # Connection configuration
    reservation_ttl: int = 3600  # seconds
    max_circuit_duration: int = 3600  # seconds
    max_circuit_bytes: int = 1024 * 1024 * 1024  # 1GB

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.limits is None:
            self.limits = RelayLimits(
                duration=self.max_circuit_duration,
                data=self.max_circuit_bytes,
                max_circuit_conns=8,
                max_reservations=4,
            )


@dataclass
class HopConfig:
    """Configuration specific to relay (hop) nodes."""

    # Resource limits per IP
    max_reservations_per_ip: int = 8
    max_circuits_per_ip: int = 16

    # Rate limiting
    reservation_rate_per_ip: int = 4  # per minute
    circuit_rate_per_ip: int = 8  # per minute

    # Resource quotas
    max_circuits_total: int = 64
    max_reservations_total: int = 32

    # Bandwidth limits
    max_bandwidth_per_circuit: int = 1024 * 1024  # 1MB/s
    max_bandwidth_total: int = 10 * 1024 * 1024  # 10MB/s


@dataclass
class ClientConfig:
    """Configuration specific to relay clients."""

    # Relay selection
    min_relay_score: float = 0.5
    max_relay_latency: float = 1.0  # seconds

    # Auto-relay settings
    enable_auto_relay: bool = True
    auto_relay_timeout: int = 30  # seconds
    max_auto_relay_attempts: int = 3

    # Reservation management
    reservation_refresh_threshold: float = 0.8  # Refresh at 80% of TTL
    max_concurrent_reservations: int = 2

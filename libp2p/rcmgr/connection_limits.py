"""
Connection limits configuration for resource management.

This module implements connection limits matching the Rust libp2p
connection-limits behavior, providing configurable limits for different
connection states and directions.
"""

from __future__ import annotations

from dataclasses import dataclass

from libp2p.rcmgr.exceptions import ResourceLimitExceeded


@dataclass
class ConnectionLimits:
    """
    Configurable connection limits matching Rust implementation.

    This class provides the same connection limit configuration as
    the Rust libp2p-connection-limits crate, allowing fine-grained
    control over connection establishment and management.
    """

    max_pending_inbound: int | None = None
    max_pending_outbound: int | None = None
    max_established_inbound: int | None = None
    max_established_outbound: int | None = None
    max_established_per_peer: int | None = None
    max_established_total: int | None = None

    def with_max_pending_inbound(self, limit: int | None) -> ConnectionLimits:
        """
        Configure the maximum number of concurrently incoming connections being
        established.

        Args:
            limit: Maximum pending inbound connections, or None for no limit

        Returns:
            ConnectionLimits for method chaining

        """
        self.max_pending_inbound = limit
        return self

    def with_max_pending_outbound(self, limit: int | None) -> ConnectionLimits:
        """
        Configure the maximum number of concurrently outgoing connections being
        established.

        Args:
            limit: Maximum pending outbound connections, or None for no limit

        Returns:
            ConnectionLimits for method chaining

        """
        self.max_pending_outbound = limit
        return self

    def with_max_established_inbound(self, limit: int | None) -> ConnectionLimits:
        """
        Configure the maximum number of concurrent established inbound connections.

        Args:
            limit: Maximum established inbound connections, or None for no limit

        Returns:
            ConnectionLimits for method chaining

        """
        self.max_established_inbound = limit
        return self

    def with_max_established_outbound(self, limit: int | None) -> ConnectionLimits:
        """
        Configure the maximum number of concurrent established outbound connections.

        Args:
            limit: Maximum established outbound connections, or None for no limit

        Returns:
            ConnectionLimits for method chaining

        """
        self.max_established_outbound = limit
        return self

    def with_max_established_per_peer(self, limit: int | None) -> ConnectionLimits:
        """
        Configure the maximum number of concurrent established connections per peer,
        regardless of direction (incoming or outgoing).

        Args:
            limit: Maximum established connections per peer, or None for no limit

        Returns:
            ConnectionLimits for method chaining

        """
        self.max_established_per_peer = limit
        return self

    def with_max_established_total(self, limit: int | None) -> ConnectionLimits:
        """
        Configure the maximum number of concurrent established connections (both
        inbound and outbound).

        Note: This should be used in conjunction with
        with_max_established_inbound() to prevent possible eclipse attacks
        (all connections being inbound).

        Args:
            limit: Maximum total established connections, or None for no limit

        Returns:
            ConnectionLimits for method chaining

        """
        self.max_established_total = limit
        return self

    def check_pending_inbound_limit(self, current: int) -> None:
        """Check if pending inbound limit would be exceeded."""
        if self.max_pending_inbound is not None and current >= self.max_pending_inbound:
            raise ResourceLimitExceeded(
                message=f"Pending inbound limit exceeded: {current} >= "
                f"{self.max_pending_inbound}"
            )

    def check_pending_outbound_limit(self, current: int) -> None:
        """Check if pending outbound limit would be exceeded."""
        if (
            self.max_pending_outbound is not None
            and current >= self.max_pending_outbound
        ):
            raise ResourceLimitExceeded(
                message=f"Pending outbound limit exceeded: {current} >= "
                f"{self.max_pending_outbound}"
            )

    def check_established_inbound_limit(self, current: int) -> None:
        """Check if established inbound limit would be exceeded."""
        if (
            self.max_established_inbound is not None
            and current >= self.max_established_inbound
        ):
            raise ResourceLimitExceeded(
                message=f"Established inbound limit exceeded: {current} >= "
                f"{self.max_established_inbound}"
            )

    def check_established_outbound_limit(self, current: int) -> None:
        """Check if established outbound limit would be exceeded."""
        if (
            self.max_established_outbound is not None
            and current >= self.max_established_outbound
        ):
            raise ResourceLimitExceeded(
                message=f"Established outbound limit exceeded: {current} >= "
                f"{self.max_established_outbound}"
            )

    def check_established_per_peer_limit(self, current: int) -> None:
        """Check if established per-peer limit would be exceeded."""
        if (
            self.max_established_per_peer is not None
            and current >= self.max_established_per_peer
        ):
            raise ResourceLimitExceeded(
                message=f"Established per peer limit exceeded: {current} >= "
                f"{self.max_established_per_peer}"
            )

    def check_established_total_limit(self, current: int) -> None:
        """Check if established total limit would be exceeded."""
        if (
            self.max_established_total is not None
            and current >= self.max_established_total
        ):
            raise ResourceLimitExceeded(
                message=f"Established total limit exceeded: {current} >= "
                f"{self.max_established_total}"
            )

    def get_limits_summary(self) -> dict[str, int | None]:
        """Get a summary of all configured limits."""
        return {
            "max_pending_inbound": self.max_pending_inbound,
            "max_pending_outbound": self.max_pending_outbound,
            "max_established_inbound": self.max_established_inbound,
            "max_established_outbound": self.max_established_outbound,
            "max_established_per_peer": self.max_established_per_peer,
            "max_established_total": self.max_established_total,
        }

    def __hash__(self) -> int:
        """Hash based on all limit values."""
        return hash(
            (
                self.max_pending_inbound,
                self.max_pending_outbound,
                self.max_established_inbound,
                self.max_established_outbound,
                self.max_established_per_peer,
                self.max_established_total,
            )
        )

    def __str__(self) -> str:
        """String representation of connection limits."""
        limits = self.get_limits_summary()
        limit_strs = [f"{k}={v}" for k, v in limits.items() if v is not None]
        return f"ConnectionLimits({', '.join(limit_strs)})"


def new_connection_limits() -> ConnectionLimits:
    """
    Create a new ConnectionLimits instance with no limits.

    Returns:
        ConnectionLimits: New instance with no limits configured

    """
    return ConnectionLimits()


def new_connection_limits_with_defaults() -> ConnectionLimits:
    """
    Create a new ConnectionLimits instance with sensible defaults.

    These defaults are based on typical libp2p usage patterns
    and provide reasonable limits for most applications.

    Returns:
        ConnectionLimits: New instance with default limits

    """
    return ConnectionLimits(
        max_pending_inbound=64,
        max_pending_outbound=64,
        max_established_inbound=256,
        max_established_outbound=256,
        max_established_per_peer=8,
        max_established_total=1024,
    )

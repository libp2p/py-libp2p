"""
Connection lifecycle management for resource management.

This module implements connection lifecycle event handling with proper
resource management integration, matching the Rust libp2p connection-limits
behavior.
"""

from __future__ import annotations

import logging
from typing import Any

import multiaddr

from libp2p.peer.id import ID

from .connection_limits import ConnectionLimits
from .connection_tracker import ConnectionId, ConnectionTracker
from .exceptions import ResourceLimitExceeded

logger = logging.getLogger(__name__)


class ConnectionLimitKind:
    """Connection limit kinds matching Rust implementation."""

    PENDING_INBOUND = "pending_inbound"
    PENDING_OUTBOUND = "pending_outbound"
    ESTABLISHED_INBOUND = "established_inbound"
    ESTABLISHED_OUTBOUND = "established_outbound"
    ESTABLISHED_PER_PEER = "established_per_peer"
    ESTABLISHED_TOTAL = "established_total"


class ConnectionLifecycleManager:
    """
    Handle connection lifecycle events with resource management.

    This class provides the same connection lifecycle handling as the Rust
    libp2p-connection-limits crate, enforcing limits at appropriate points
    in the connection lifecycle.
    """

    def __init__(
        self,
        tracker: ConnectionTracker,
        limits: ConnectionLimits,
    ):
        """
        Initialize connection lifecycle manager.

        Args:
            tracker: Connection state tracker
            limits: Connection limits to enforce

        """
        self.tracker = tracker
        self.limits = limits

        logger.debug(f"Initialized ConnectionLifecycleManager with limits: {limits}")

    async def handle_pending_inbound_connection(
        self,
        connection_id: ConnectionId,
        local_addr: multiaddr.Multiaddr,
        remote_addr: multiaddr.Multiaddr,
        peer_id: ID | None = None,
    ) -> None:
        """
        Handle pending inbound connection with limit checking.

        This method checks if the connection should be allowed based on
        pending inbound limits and bypass rules.

        Args:
            connection_id: Unique connection identifier
            local_addr: Local address
            remote_addr: Remote address
            peer_id: Peer ID if known

        Raises:
            ResourceLimitExceeded: If connection would exceed limits

        """
        logger.debug(f"Handling pending inbound connection {connection_id}")

        # Check if peer is bypassed
        if peer_id and self.tracker.is_bypassed(peer_id):
            logger.debug(f"Peer {peer_id} is bypassed, allowing connection")
            self.tracker.add_pending_inbound(connection_id, peer_id)
            return

        # Check pending inbound limit
        current_pending = self.tracker.get_connection_count("pending_inbound")
        if not self.limits.check_pending_inbound_limit(current_pending):
            raise ResourceLimitExceeded(
                f"Pending inbound connection limit exceeded: "
                f"current={current_pending}, limit={self.limits.max_pending_inbound}"
            )

        # Add to tracking
        self.tracker.add_pending_inbound(connection_id, peer_id)
        logger.debug(f"Added pending inbound connection {connection_id}")

    async def handle_established_inbound_connection(
        self,
        connection_id: ConnectionId,
        peer_id: ID,
        local_addr: multiaddr.Multiaddr,
        remote_addr: multiaddr.Multiaddr,
    ) -> None:
        """
        Handle established inbound connection with limit checking.

        This method checks if the connection should be allowed based on
        established inbound limits, per-peer limits, and total limits.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID for the connection
            local_addr: Local address
            remote_addr: Remote address

        Raises:
            ResourceLimitExceeded: If connection would exceed limits

        """
        logger.debug(
            f"Handling established inbound connection {connection_id} "
            f"for peer {peer_id}"
        )

        # Check if peer is bypassed
        if self.tracker.is_bypassed(peer_id):
            logger.debug(f"Peer {peer_id} is bypassed, allowing connection")
            self.tracker.move_to_established_inbound(connection_id, peer_id)
            return

        # Check established inbound limit
        current_established_inbound = self.tracker.get_connection_count(
            "established_inbound"
        )
        if not self.limits.check_established_inbound_limit(current_established_inbound):
            raise ResourceLimitExceeded(
                f"Established inbound connection limit exceeded: "
                f"current={current_established_inbound}, "
                f"limit={self.limits.max_established_inbound}"
            )

        # Check per-peer limit
        current_per_peer = self.tracker.get_peer_connection_count(peer_id)
        if not self.limits.check_established_per_peer_limit(current_per_peer):
            raise ResourceLimitExceeded(
                f"Established per-peer connection limit exceeded for peer {peer_id}: "
                f"current={current_per_peer}, "
                f"limit={self.limits.max_established_per_peer}"
            )

        # Check total established limit
        current_total = self.tracker.get_connection_count("established_total")
        if not self.limits.check_established_total_limit(current_total):
            raise ResourceLimitExceeded(
                f"Established total connection limit exceeded: "
                f"current={current_total}, limit={self.limits.max_established_total}"
            )

        # Move to established
        self.tracker.move_to_established_inbound(connection_id, peer_id)
        logger.debug(f"Moved connection {connection_id} to established inbound")

    async def handle_pending_outbound_connection(
        self,
        connection_id: ConnectionId,
        peer_id: ID | None,
        addresses: list[multiaddr.Multiaddr],
        endpoint: str,
    ) -> None:
        """
        Handle pending outbound connection with limit checking.

        This method checks if the connection should be allowed based on
        pending outbound limits and bypass rules.

        Args:
            connection_id: Unique connection identifier
            peer_id: Peer ID if known
            addresses: List of addresses to dial
            endpoint: Endpoint type

        Raises:
            ResourceLimitExceeded: If connection would exceed limits

        """
        logger.debug(f"Handling pending outbound connection {connection_id}")

        # Check if peer is bypassed
        if peer_id and self.tracker.is_bypassed(peer_id):
            logger.debug(f"Peer {peer_id} is bypassed, allowing connection")
            self.tracker.add_pending_outbound(connection_id, peer_id)
            return

        # Check pending outbound limit
        current_pending = self.tracker.get_connection_count("pending_outbound")
        if not self.limits.check_pending_outbound_limit(current_pending):
            raise ResourceLimitExceeded(
                f"Pending outbound connection limit exceeded: "
                f"current={current_pending}, limit={self.limits.max_pending_outbound}"
            )

        # Add to tracking
        self.tracker.add_pending_outbound(connection_id, peer_id)
        logger.debug(f"Added pending outbound connection {connection_id}")

    async def handle_established_outbound_connection(
        self,
        connection_id: ConnectionId,
        peer_id: ID,
        local_addr: multiaddr.Multiaddr,
        endpoint: str,
    ) -> None:
        """
        Handle established outbound connection with limit checking.

        This method checks if the connection should be allowed based on
        established outbound limits, per-peer limits, and total limits.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID for the connection
            local_addr: Local address
            endpoint: Endpoint type

        Raises:
            ResourceLimitExceeded: If connection would exceed limits

        """
        logger.debug(
            f"Handling established outbound connection {connection_id} "
            f"for peer {peer_id}"
        )

        # Check if peer is bypassed
        if self.tracker.is_bypassed(peer_id):
            logger.debug(f"Peer {peer_id} is bypassed, allowing connection")
            self.tracker.move_to_established_outbound(connection_id, peer_id)
            return

        # Check established outbound limit
        current_established_outbound = self.tracker.get_connection_count(
            "established_outbound"
        )
        if not self.limits.check_established_outbound_limit(
            current_established_outbound
        ):
            raise ResourceLimitExceeded(
                f"Established outbound connection limit exceeded: "
                f"current={current_established_outbound}, "
                f"limit={self.limits.max_established_outbound}"
            )

        # Check per-peer limit
        current_per_peer = self.tracker.get_peer_connection_count(peer_id)
        if not self.limits.check_established_per_peer_limit(current_per_peer):
            raise ResourceLimitExceeded(
                f"Established per-peer connection limit exceeded for peer {peer_id}: "
                f"current={current_per_peer}, "
                f"limit={self.limits.max_established_per_peer}"
            )

        # Check total established limit
        current_total = self.tracker.get_connection_count("established_total")
        if not self.limits.check_established_total_limit(current_total):
            raise ResourceLimitExceeded(
                f"Established total connection limit exceeded: "
                f"current={current_total}, limit={self.limits.max_established_total}"
            )

        # Move to established
        self.tracker.move_to_established_outbound(connection_id, peer_id)
        logger.debug(f"Moved connection {connection_id} to established outbound")

    async def handle_connection_closed(
        self,
        connection_id: ConnectionId,
        peer_id: ID | None = None,
        reason: str = "unknown",
    ) -> None:
        """
        Handle connection closed event.

        This method removes the connection from all tracking and updates
        statistics.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID if known
            reason: Reason for connection closure

        """
        logger.debug(f"Handling connection closed {connection_id}, reason: {reason}")

        # Remove from tracking
        self.tracker.remove_connection(connection_id, peer_id)
        logger.debug(f"Removed connection {connection_id} from tracking")

    def get_connection_stats(self) -> dict[str, Any]:
        """
        Get connection statistics.

        Returns:
            Dictionary of connection statistics

        """
        return self.tracker.get_stats()

    def get_limits_summary(self) -> dict[str, int | None]:
        """
        Get connection limits summary.

        Returns:
            Dictionary of connection limits

        """
        return self.limits.get_limits_summary()

    def __str__(self) -> str:
        """String representation of lifecycle manager."""
        return (
            f"ConnectionLifecycleManager(tracker={self.tracker}, limits={self.limits})"
        )

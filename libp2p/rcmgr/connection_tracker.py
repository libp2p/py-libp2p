"""
Connection state tracking for resource management.

This module implements connection state tracking matching the Rust libp2p
connection-limits behavior, providing comprehensive tracking of connection
states and per-peer connection counting.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import threading
import time
from typing import Any

from libp2p.peer.id import ID

from .connection_limits import ConnectionLimits

# Type alias for connection IDs
ConnectionId = str


@dataclass
class ConnectionInfo:
    """Information about a tracked connection."""

    connection_id: ConnectionId
    peer_id: ID | None
    direction: str  # "inbound" or "outbound"
    state: str  # "pending" or "established"
    created_at: float
    established_at: float | None = None

    @property
    def is_pending(self) -> bool:
        """Check if connection is in pending state."""
        return self.state == "pending"

    @property
    def is_established(self) -> bool:
        """Check if connection is in established state."""
        return self.state == "established"

    @property
    def is_inbound(self) -> bool:
        """Check if connection is inbound."""
        return self.direction == "inbound"

    @property
    def is_outbound(self) -> bool:
        """Check if connection is outbound."""
        return self.direction == "outbound"


class ConnectionTracker:
    """
    Track connection states like Rust implementation.

    This class provides the same connection state tracking as the Rust
    libp2p-connection-limits crate, maintaining sets of connections in
    different states and providing per-peer connection counting.
    """

    def __init__(self, limits: ConnectionLimits | None = None):
        """
        Initialize connection tracker.

        Args:
            limits: Connection limits to enforce, or None for no limits

        """
        self.limits = limits or ConnectionLimits()

        # Thread safety
        self._lock = threading.RLock()

        # Connection state sets (matching Rust implementation)
        self.pending_inbound: set[ConnectionId] = set()
        self.pending_outbound: set[ConnectionId] = set()
        self.established_inbound: set[ConnectionId] = set()
        self.established_outbound: set[ConnectionId] = set()
        self.established_per_peer: dict[ID, set[ConnectionId]] = {}

        # Bypass tracking (matching Rust implementation)
        self.bypass_peers: set[ID] = set()

        # Connection information storage
        self._connections: dict[ConnectionId, ConnectionInfo] = {}

        # Statistics
        self._stats = {
            "total_connections_created": 0,
            "total_connections_established": 0,
            "total_connections_closed": 0,
            "peak_pending_inbound": 0,
            "peak_pending_outbound": 0,
            "peak_established_inbound": 0,
            "peak_established_outbound": 0,
        }

    def add_bypass_peer(self, peer_id: ID) -> None:
        """
        Add a peer to the bypass list.

        Connections to bypassed peers will not be counted toward limits.

        Args:
            peer_id: Peer ID to bypass limits for

        """
        with self._lock:
            self.bypass_peers.add(peer_id)

    def remove_bypass_peer(self, peer_id: ID) -> None:
        """
        Remove a peer from the bypass list.

        Args:
            peer_id: Peer ID to remove from bypass list

        """
        with self._lock:
            self.bypass_peers.discard(peer_id)

    def is_bypassed(self, peer_id: ID) -> bool:
        """
        Check if a peer is bypassed.

        Args:
            peer_id: Peer ID to check

        Returns:
            True if peer is bypassed, False otherwise

        """
        with self._lock:
            return peer_id in self.bypass_peers

    def add_pending_inbound(
        self, connection_id: ConnectionId, peer_id: ID | None = None
    ) -> None:
        """
        Add a pending inbound connection.

        Args:
            connection_id: Unique connection identifier
            peer_id: Peer ID if known

        """
        with self._lock:
            self.pending_inbound.add(connection_id)
            self._connections[connection_id] = ConnectionInfo(
                connection_id=connection_id,
                peer_id=peer_id,
                direction="inbound",
                state="pending",
                created_at=time.time(),
            )
            self._stats["total_connections_created"] += 1
            self._stats["peak_pending_inbound"] = max(
                self._stats["peak_pending_inbound"], len(self.pending_inbound)
            )

    def add_pending_outbound(
        self, connection_id: ConnectionId, peer_id: ID | None = None
    ) -> None:
        """
        Add a pending outbound connection.

        Args:
            connection_id: Unique connection identifier
            peer_id: Peer ID if known

        """
        with self._lock:
            self.pending_outbound.add(connection_id)
            self._connections[connection_id] = ConnectionInfo(
                connection_id=connection_id,
                peer_id=peer_id,
                direction="outbound",
                state="pending",
                created_at=time.time(),
            )
            self._stats["total_connections_created"] += 1
            self._stats["peak_pending_outbound"] = max(
                self._stats["peak_pending_outbound"], len(self.pending_outbound)
            )

    def move_to_established_inbound(
        self, connection_id: ConnectionId, peer_id: ID
    ) -> None:
        """
        Move a connection from pending to established inbound.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID for the connection

        """
        with self._lock:
            # Remove from pending
            self.pending_inbound.discard(connection_id)

            # Add to established
            self.established_inbound.add(connection_id)

            # Update per-peer tracking
            if peer_id not in self.established_per_peer:
                self.established_per_peer[peer_id] = set()
            self.established_per_peer[peer_id].add(connection_id)

            # Update connection info
            if connection_id in self._connections:
                self._connections[connection_id].state = "established"
                self._connections[connection_id].peer_id = peer_id
                self._connections[connection_id].established_at = time.time()

            self._stats["total_connections_established"] += 1
            self._stats["peak_established_inbound"] = max(
                self._stats["peak_established_inbound"], len(self.established_inbound)
            )

    def move_to_established_outbound(
        self, connection_id: ConnectionId, peer_id: ID
    ) -> None:
        """
        Move a connection from pending to established outbound.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID for the connection

        """
        with self._lock:
            # Remove from pending
            self.pending_outbound.discard(connection_id)

            # Add to established
            self.established_outbound.add(connection_id)

            # Update per-peer tracking
            if peer_id not in self.established_per_peer:
                self.established_per_peer[peer_id] = set()
            self.established_per_peer[peer_id].add(connection_id)

            # Update connection info
            if connection_id in self._connections:
                self._connections[connection_id].state = "established"
                self._connections[connection_id].peer_id = peer_id
                self._connections[connection_id].established_at = time.time()

            self._stats["total_connections_established"] += 1
            self._stats["peak_established_outbound"] = max(
                self._stats["peak_established_outbound"], len(self.established_outbound)
            )

    def remove_connection(
        self, connection_id: ConnectionId, peer_id: ID | None = None
    ) -> None:
        """
        Remove a connection from all tracking.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID if known (for per-peer cleanup)

        """
        with self._lock:
            # Remove from all sets
            self.pending_inbound.discard(connection_id)
            self.pending_outbound.discard(connection_id)
            self.established_inbound.discard(connection_id)
            self.established_outbound.discard(connection_id)

            # Remove from per-peer tracking
            if peer_id and peer_id in self.established_per_peer:
                self.established_per_peer[peer_id].discard(connection_id)
                if not self.established_per_peer[peer_id]:
                    del self.established_per_peer[peer_id]

            # Remove connection info
            self._connections.pop(connection_id, None)

            self._stats["total_connections_closed"] += 1

    def get_connection_count(self, kind: str) -> int:
        """
        Get connection count for a specific kind.

        Args:
            kind: Connection kind ("pending_inbound", "pending_outbound",
                  "established_inbound", "established_outbound", "established_total")

        Returns:
            Number of connections of the specified kind

        """
        with self._lock:
            if kind == "pending_inbound":
                return len(self.pending_inbound)
            elif kind == "pending_outbound":
                return len(self.pending_outbound)
            elif kind == "established_inbound":
                return len(self.established_inbound)
            elif kind == "established_outbound":
                return len(self.established_outbound)
            elif kind == "established_total":
                return len(self.established_inbound) + len(self.established_outbound)
            else:
                raise ValueError(f"Unknown connection kind: {kind}")

    def get_peer_connection_count(self, peer_id: ID) -> int:
        """
        Get connection count for a specific peer.

        Args:
            peer_id: Peer ID to count connections for

        Returns:
            Number of established connections for the peer

        """
        with self._lock:
            return len(self.established_per_peer.get(peer_id, set()))

    def get_connection_info(self, connection_id: ConnectionId) -> ConnectionInfo | None:
        """
        Get information about a specific connection.

        Args:
            connection_id: Connection identifier

        Returns:
            ConnectionInfo if found, None otherwise

        """
        with self._lock:
            return self._connections.get(connection_id)

    def get_all_connections(self) -> list[ConnectionInfo]:
        """
        Get information about all tracked connections.

        Returns:
            List of all connection information

        """
        with self._lock:
            return list(self._connections.values())

    def get_stats(self) -> dict[str, Any]:
        """
        Get connection tracking statistics.

        Returns:
            Dictionary of statistics

        """
        with self._lock:
            return {
                **self._stats,
                "current_pending_inbound": len(self.pending_inbound),
                "current_pending_outbound": len(self.pending_outbound),
                "current_established_inbound": len(self.established_inbound),
                "current_established_outbound": len(self.established_outbound),
                "current_established_total": (
                    len(self.established_inbound) + len(self.established_outbound)
                ),
                "current_peers_with_connections": len(self.established_per_peer),
                "bypass_peers_count": len(self.bypass_peers),
            }

    def clear(self) -> None:
        """Clear all connection tracking."""
        with self._lock:
            self.pending_inbound.clear()
            self.pending_outbound.clear()
            self.established_inbound.clear()
            self.established_outbound.clear()
            self.established_per_peer.clear()
            self._connections.clear()
            self.bypass_peers.clear()

    def __str__(self) -> str:
        """String representation of connection tracker."""
        stats = self.get_stats()
        return (
            f"ConnectionTracker("
            f"pending_inbound={stats['current_pending_inbound']}, "
            f"pending_outbound={stats['current_pending_outbound']}, "
            f"established_inbound={stats['current_established_inbound']}, "
            f"established_outbound={stats['current_established_outbound']}, "
            f"established_total={stats['current_established_total']}, "
            f"peers={stats['current_peers_with_connections']})"
        )

    def __repr__(self) -> str:
        """Repr representation of connection tracker."""
        return self.__str__()

    def __hash__(self) -> int:
        """Hash based on limits and current state."""
        with self._lock:
            return hash(
                (
                    id(self.limits),
                    len(self.pending_inbound),
                    len(self.pending_outbound),
                    len(self.established_inbound),
                    len(self.established_outbound),
                    len(self.established_per_peer),
                    len(self.bypass_peers),
                )
            )

    def __eq__(self, other: Any) -> bool:
        """Equality based on limits and current state."""
        if not isinstance(other, ConnectionTracker):
            return False

        with self._lock:
            with other._lock:
                return (
                    self.limits == other.limits
                    and self.pending_inbound == other.pending_inbound
                    and self.pending_outbound == other.pending_outbound
                    and self.established_inbound == other.established_inbound
                    and self.established_outbound == other.established_outbound
                    and self.established_per_peer == other.established_per_peer
                    and self.bypass_peers == other.bypass_peers
                )

    def __copy__(self) -> ConnectionTracker:
        """Shallow copy of connection tracker."""
        new_tracker = ConnectionTracker(self.limits)
        with self._lock:
            new_tracker.pending_inbound = self.pending_inbound.copy()
            new_tracker.pending_outbound = self.pending_outbound.copy()
            new_tracker.established_inbound = self.established_inbound.copy()
            new_tracker.established_outbound = self.established_outbound.copy()
            new_tracker.established_per_peer = {
                peer_id: conns.copy()
                for peer_id, conns in self.established_per_peer.items()
            }
            new_tracker.bypass_peers = self.bypass_peers.copy()
            new_tracker._connections = self._connections.copy()
            new_tracker._stats = self._stats.copy()
        return new_tracker

    def __deepcopy__(self, memo: dict[Any, Any]) -> ConnectionTracker:
        """Deep copy of connection tracker."""
        new_tracker = ConnectionTracker(self.limits)
        with self._lock:
            new_tracker.pending_inbound = self.pending_inbound.copy()
            new_tracker.pending_outbound = self.pending_outbound.copy()
            new_tracker.established_inbound = self.established_inbound.copy()
            new_tracker.established_outbound = self.established_outbound.copy()
            new_tracker.established_per_peer = {
                peer_id: conns.copy()
                for peer_id, conns in self.established_per_peer.items()
            }
            new_tracker.bypass_peers = self.bypass_peers.copy()
            new_tracker._connections = {
                conn_id: copy.deepcopy(conn_info, memo)
                for conn_id, conn_info in self._connections.items()
            }
            new_tracker._stats = self._stats.copy()
        return new_tracker

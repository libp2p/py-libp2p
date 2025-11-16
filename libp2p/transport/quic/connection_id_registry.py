"""
Connection ID Registry for QUIC Listener.

Manages all Connection ID routing state and mappings to ensure consistency
and simplify packet routing logic in the QUIC listener.

This class encapsulates the four synchronized dictionaries that track:
- Established connections (by Connection ID)
- Pending connections (by Connection ID)
- Connection ID to address mappings
- Address to Connection ID mappings
"""

import logging
from typing import TYPE_CHECKING

import trio

if TYPE_CHECKING:
    from aioquic.quic.connection import QuicConnection

    from .connection import QUICConnection

logger = logging.getLogger(__name__)


class ConnectionIDRegistry:
    """
    Registry for managing Connection ID mappings in QUIC listener.

    Encapsulates all Connection ID routing state to ensure consistency
    and simplify the listener's packet routing logic. All operations
    maintain synchronization across the four internal dictionaries.

    This follows the pattern established by ConnectionTracker in the codebase.
    """

    def __init__(self, lock: trio.Lock):
        """
        Initialize Connection ID registry.

        Args:
            lock: The trio.Lock to use for thread-safe operations.
                 Should be the same lock used by the listener.

        """
        # Established connections: Connection ID -> QUICConnection
        self._connections: dict[bytes, "QUICConnection"] = {}

        # Pending connections: Connection ID -> QuicConnection (aioquic)
        self._pending: dict[bytes, "QuicConnection"] = {}

        # Connection ID -> address mapping
        self._cid_to_addr: dict[bytes, tuple[str, int]] = {}

        # Address -> Connection ID mapping
        self._addr_to_cid: dict[tuple[str, int], bytes] = {}

        # Lock for thread-safe operations
        self._lock = lock

    async def find_by_cid(
        self, cid: bytes
    ) -> tuple["QUICConnection | None", "QuicConnection | None", bool]:
        """
        Find connection by Connection ID.

        Args:
            cid: Connection ID to look up

        Returns:
            Tuple of (established_connection, pending_connection, is_pending)
            - If found in established: (connection, None, False)
            - If found in pending: (None, quic_conn, True)
            - If not found: (None, None, False)

        """
        async with self._lock:
            if cid in self._connections:
                return (self._connections[cid], None, False)
            elif cid in self._pending:
                return (None, self._pending[cid], True)
            else:
                return (None, None, False)

    async def find_by_address(
        self, addr: tuple[str, int]
    ) -> tuple["QUICConnection | None", bytes | None]:
        """
        Find connection by address with fallback search.

        This implements the fallback routing mechanism for cases where
        packets arrive with new Connection IDs before ConnectionIdIssued
        events are processed.

        Strategy:
        1. Try address-to-CID lookup (O(1))
        2. Fallback to linear search through all connections (O(n))

        Args:
            addr: Remote address (host, port) tuple

        Returns:
            Tuple of (connection, original_cid) or (None, None) if not found

        """
        async with self._lock:
            # Strategy 1: Try address-to-CID lookup (O(1))
            original_cid = self._addr_to_cid.get(addr)
            if original_cid:
                connection = self._connections.get(original_cid)
                if connection:
                    return (connection, original_cid)
                else:
                    # Address mapping exists but connection not found
                    # Clean up stale mapping
                    del self._addr_to_cid[addr]
                    return (None, None)

            # Strategy 2: Linear search through all connections (O(n))
            # NOTE: This is O(n) but only used as last-resort fallback when:
            # 1. Connection ID is unknown
            # 2. Address-to-CID lookup failed
            # 3. Proactive notification hasn't occurred yet
            for cid, conn in self._connections.items():
                if hasattr(conn, "_remote_addr") and conn._remote_addr == addr:
                    return (conn, cid)

            return (None, None)

    async def register_connection(
        self, cid: bytes, connection: "QUICConnection", addr: tuple[str, int]
    ) -> None:
        """
        Register an established connection.

        Args:
            cid: Connection ID for this connection
            connection: The QUICConnection instance
            addr: Remote address (host, port) tuple

        """
        async with self._lock:
            self._connections[cid] = connection
            self._cid_to_addr[cid] = addr
            self._addr_to_cid[addr] = cid

    async def register_pending(
        self, cid: bytes, quic_conn: "QuicConnection", addr: tuple[str, int]
    ) -> None:
        """
        Register a pending (handshaking) connection.

        Args:
            cid: Connection ID for this pending connection
            quic_conn: The aioquic QuicConnection instance
            addr: Remote address (host, port) tuple

        """
        async with self._lock:
            self._pending[cid] = quic_conn
            self._cid_to_addr[cid] = addr
            self._addr_to_cid[addr] = cid

    async def add_connection_id(self, new_cid: bytes, existing_cid: bytes) -> None:
        """
        Add a new Connection ID for an existing connection.

        This is called when a ConnectionIdIssued event is received.
        The new Connection ID is mapped to the same address and connection
        as the existing Connection ID.

        Args:
            new_cid: New Connection ID to register
            existing_cid: Existing Connection ID that's already registered

        """
        async with self._lock:
            # Get address from existing CID
            addr = self._cid_to_addr.get(existing_cid)
            if not addr:
                logger.warning(
                    f"Could not find address for existing Connection ID "
                    f"{existing_cid.hex()[:8]} when adding new Connection ID "
                    f"{new_cid.hex()[:8]}"
                )
                return

            # Map new CID to the same address
            self._cid_to_addr[new_cid] = addr

            # If connection is already promoted, also map new CID to the connection
            if existing_cid in self._connections:
                connection = self._connections[existing_cid]
                self._connections[new_cid] = connection
                logger.debug(
                    f"Registered new Connection ID {new_cid.hex()[:8]} "
                    f"for existing connection {existing_cid.hex()[:8]} "
                    f"at address {addr}"
                )

    async def remove_connection_id(self, cid: bytes) -> tuple[str, int] | None:
        """
        Remove a Connection ID and clean up all related mappings.

        Args:
            cid: Connection ID to remove

        Returns:
            The address that was associated with this Connection ID, or None

        """
        async with self._lock:
            # Remove from both established and pending
            self._connections.pop(cid, None)
            self._pending.pop(cid, None)

            # Get and remove address mapping
            addr = self._cid_to_addr.pop(cid, None)
            if addr:
                # Only remove addr mapping if this was the active CID
                if self._addr_to_cid.get(addr) == cid:
                    del self._addr_to_cid[addr]

            return addr

    async def remove_pending_connection(self, cid: bytes) -> None:
        """
        Remove a pending connection and clean up mappings.

        Args:
            cid: Connection ID of pending connection to remove

        """
        async with self._lock:
            self._pending.pop(cid, None)
            addr = self._cid_to_addr.pop(cid, None)
            if addr:
                if self._addr_to_cid.get(addr) == cid:
                    del self._addr_to_cid[addr]

    async def remove_by_address(self, addr: tuple[str, int]) -> bytes | None:
        """
        Remove connection by address.

        Args:
            addr: Remote address (host, port) tuple

        Returns:
            The Connection ID that was associated with this address, or None

        """
        async with self._lock:
            cid = self._addr_to_cid.pop(addr, None)
            if cid:
                self._connections.pop(cid, None)
                self._pending.pop(cid, None)
                self._cid_to_addr.pop(cid, None)
            return cid

    async def promote_pending(self, cid: bytes, connection: "QUICConnection") -> None:
        """
        Promote a pending connection to established.

        Moves the connection from pending to established while maintaining
        all address mappings.

        Args:
            cid: Connection ID of the connection to promote
            connection: The QUICConnection instance to register

        """
        async with self._lock:
            # Remove from pending
            self._pending.pop(cid, None)

            # Add to established (may already exist, that's OK)
            if cid in self._connections:
                logger.warning(
                    f"Connection {cid.hex()[:8]} already exists in "
                    f"_connections! Reusing existing connection."
                )
            else:
                self._connections[cid] = connection

            # Ensure address mappings are up to date
            # (they should already exist from when pending was registered)
            if cid in self._cid_to_addr:
                addr = self._cid_to_addr[cid]
                self._addr_to_cid[addr] = cid

    async def register_new_cid_for_existing_connection(
        self, new_cid: bytes, connection: "QUICConnection", addr: tuple[str, int]
    ) -> None:
        """
        Register a new Connection ID for an existing connection.

        This is used by the fallback routing mechanism when a packet
        with a new Connection ID arrives before the ConnectionIdIssued
        event is processed.

        Args:
            new_cid: New Connection ID to register
            connection: The existing QUICConnection instance
            addr: Remote address (host, port) tuple

        """
        async with self._lock:
            self._connections[new_cid] = connection
            self._cid_to_addr[new_cid] = addr
            # Update addr mapping to use new CID
            self._addr_to_cid[addr] = new_cid
            logger.debug(
                f"Registered new Connection ID {new_cid.hex()[:8]} "
                f"for existing connection at address {addr} "
                f"(fallback mechanism)"
            )

    async def get_all_cids_for_connection(
        self, connection: "QUICConnection"
    ) -> list[bytes]:
        """
        Get all Connection IDs associated with a connection object.

        This is used by the connection's notification method to find
        which Connection IDs need to be updated.

        Args:
            connection: The QUICConnection instance

        Returns:
            List of Connection IDs associated with this connection

        """
        async with self._lock:
            cids = []
            for cid, conn in self._connections.items():
                if conn is connection:
                    cids.append(cid)
            return cids

    async def cleanup_stale_address_mapping(self, addr: tuple[str, int]) -> None:
        """
        Clean up a stale address mapping.

        Used when address mapping exists but connection is not found.

        Args:
            addr: Address to clean up

        """
        async with self._lock:
            self._addr_to_cid.pop(addr, None)

    def __len__(self) -> int:
        """Return total number of connections (established + pending)."""
        return len(self._connections) + len(self._pending)

    async def get_all_established_cids(self) -> list[bytes]:
        """
        Get all Connection IDs for established connections.

        Returns:
            List of Connection IDs for established connections

        """
        async with self._lock:
            return list(self._connections.keys())

    async def get_all_pending_cids(self) -> list[bytes]:
        """
        Get all Connection IDs for pending connections.

        Returns:
            List of Connection IDs for pending connections

        """
        async with self._lock:
            return list(self._pending.keys())

    def get_stats(self) -> dict[str, int]:
        """
        Get registry statistics.

        Returns:
            Dictionary with connection counts

        """
        return {
            "established_connections": len(self._connections),
            "pending_connections": len(self._pending),
            "total_connection_ids": len(self._cid_to_addr),
            "address_mappings": len(self._addr_to_cid),
        }

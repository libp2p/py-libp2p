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
        # Initial CIDs (for handshake packets) - separate from established
        # (inspired by quinn)
        # Maps initial destination CID to pending QuicConnection
        self._initial_cids: dict[bytes, "QuicConnection"] = {}

        # Established connections: Connection ID -> QUICConnection
        self._connections: dict[bytes, "QUICConnection"] = {}

        # Pending connections: Connection ID -> QuicConnection (aioquic)
        self._pending: dict[bytes, "QuicConnection"] = {}

        # Connection ID -> address mapping
        self._cid_to_addr: dict[bytes, tuple[str, int]] = {}

        # Address -> Connection ID mapping
        self._addr_to_cid: dict[tuple[str, int], bytes] = {}

        # Reverse mapping: Connection -> address (for O(1) fallback routing,
        # inspired by quinn)
        self._connection_addresses: dict["QUICConnection", tuple[str, int]] = {}

        # Sequence number tracking (inspired by quinn's architecture)
        # CID -> sequence number mapping
        self._cid_sequences: dict[bytes, int] = {}
        # Connection -> sequence -> CID mapping (for retirement ordering)
        self._connection_sequences: dict["QUICConnection", dict[int, bytes]] = {}

        # Lock for thread-safe operations
        self._lock = lock

    async def find_by_cid(
        self, cid: bytes, is_initial: bool = False
    ) -> tuple["QUICConnection | None", "QuicConnection | None", bool]:
        """
        Find connection by Connection ID.

        Args:
            cid: Connection ID to look up
            is_initial: Whether this is an initial packet (checks _initial_cids first)

        Returns:
            Tuple of (established_connection, pending_connection, is_pending)
            - If found in established: (connection, None, False)
            - If found in pending: (None, quic_conn, True)
            - If found in initial: (None, quic_conn, True)
            - If not found: (None, None, False)

        """
        async with self._lock:
            # For initial packets, check initial CIDs first (inspired by quinn)
            if is_initial and cid in self._initial_cids:
                return (None, self._initial_cids[cid], True)

            # Check established connections
            if cid in self._connections:
                return (self._connections[cid], None, False)
            # Check pending connections
            elif cid in self._pending:
                return (None, self._pending[cid], True)
            else:
                return (None, None, False)

    async def find_by_address(
        self, addr: tuple[str, int]
    ) -> tuple["QUICConnection | None", bytes | None]:
        """
        Find connection by address with O(1) lookup (inspired by quinn).

        This implements the fallback routing mechanism for cases where
        packets arrive with new Connection IDs before ConnectionIdIssued
        events are processed.

        Strategy (all O(1)):
        1. Try address-to-CID lookup
        2. Try connection-to-address reverse mapping

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

            # Strategy 2: Try reverse mapping connection -> address (O(1))
            # This is more efficient than linear search and handles cases where
            # address-to-CID mapping might be stale but connection exists
            for connection, connection_addr in self._connection_addresses.items():
                if connection_addr == addr:
                    # Find a CID for this connection
                    for cid, conn in self._connections.items():
                        if conn is connection:
                            return (connection, cid)
                    # If no CID found, still return connection (CID will be set later)
                    return (connection, None)

            return (None, None)

    async def register_connection(
        self,
        cid: bytes,
        connection: "QUICConnection",
        addr: tuple[str, int],
        sequence: int = 0,
    ) -> None:
        """
        Register an established connection.

        Args:
            cid: Connection ID for this connection
            connection: The QUICConnection instance
            addr: Remote address (host, port) tuple
            sequence: Sequence number for this Connection ID (default: 0)

        """
        async with self._lock:
            self._connections[cid] = connection
            self._cid_to_addr[cid] = addr
            self._addr_to_cid[addr] = cid

            # Maintain reverse mapping for O(1) fallback routing
            self._connection_addresses[connection] = addr

            # Track sequence number
            self._cid_sequences[cid] = sequence
            if connection not in self._connection_sequences:
                self._connection_sequences[connection] = {}
            self._connection_sequences[connection][sequence] = cid

    async def register_pending(
        self,
        cid: bytes,
        quic_conn: "QuicConnection",
        addr: tuple[str, int],
        sequence: int = 0,
    ) -> None:
        """
        Register a pending (handshaking) connection.

        Args:
            cid: Connection ID for this pending connection
            quic_conn: The aioquic QuicConnection instance
            addr: Remote address (host, port) tuple
            sequence: Sequence number for this Connection ID (default: 0)

        """
        async with self._lock:
            self._pending[cid] = quic_conn
            self._cid_to_addr[cid] = addr
            self._addr_to_cid[addr] = cid

            # Track sequence number (will be moved to connection sequences
            # when promoted)
            self._cid_sequences[cid] = sequence

    async def add_connection_id(
        self, new_cid: bytes, existing_cid: bytes, sequence: int
    ) -> None:
        """
        Add a new Connection ID for an existing connection.

        This is called when a ConnectionIdIssued event is received.
        The new Connection ID is mapped to the same address and connection
        as the existing Connection ID.

        Args:
            new_cid: New Connection ID to register
            existing_cid: Existing Connection ID that's already registered
            sequence: Sequence number for the new Connection ID

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

            # Track sequence number
            self._cid_sequences[new_cid] = sequence

            # If connection is already promoted, also map new CID to the connection
            if existing_cid in self._connections:
                connection = self._connections[existing_cid]
                self._connections[new_cid] = connection

                # Track sequence for this connection
                if connection not in self._connection_sequences:
                    self._connection_sequences[connection] = {}
                self._connection_sequences[connection][sequence] = new_cid

                logger.debug(
                    f"Registered new Connection ID {new_cid.hex()[:8]} "
                    f"(sequence {sequence}) for existing connection "
                    f"{existing_cid.hex()[:8]} at address {addr}"
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
            # Get connection and sequence before removal
            connection = self._connections.get(cid)
            sequence = self._cid_sequences.get(cid)

            # Remove from initial, established, and pending
            self._initial_cids.pop(cid, None)
            self._connections.pop(cid, None)
            self._pending.pop(cid, None)

            # Get and remove address mapping
            addr = self._cid_to_addr.pop(cid, None)
            if addr:
                # Only remove addr mapping if this was the active CID
                if self._addr_to_cid.get(addr) == cid:
                    del self._addr_to_cid[addr]

            # Clean up sequence mappings
            if sequence is not None:
                self._cid_sequences.pop(cid, None)
                if connection and connection in self._connection_sequences:
                    self._connection_sequences[connection].pop(sequence, None)
                    # Clean up empty connection sequences dict
                    if not self._connection_sequences[connection]:
                        del self._connection_sequences[connection]

            # Clean up reverse mapping if this was the last CID for the connection
            if connection:
                # Check if connection has any other CIDs
                has_other_cids = any(
                    c != cid and conn is connection
                    for c, conn in self._connections.items()
                )
                if not has_other_cids:
                    self._connection_addresses.pop(connection, None)

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

            # Clean up sequence mapping
            self._cid_sequences.pop(cid, None)

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
                connection = self._connections.get(cid)
                self._initial_cids.pop(cid, None)
                self._connections.pop(cid, None)
                self._pending.pop(cid, None)
                self._cid_to_addr.pop(cid, None)
                # Clean up reverse mapping
                if connection:
                    # Check if connection has any other CIDs
                    has_other_cids = any(
                        c != cid and conn is connection
                        for c, conn in self._connections.items()
                    )
                    if not has_other_cids:
                        self._connection_addresses.pop(connection, None)
            return cid

    async def promote_pending(self, cid: bytes, connection: "QUICConnection") -> None:
        """
        Promote a pending connection to established.

        Moves the connection from pending to established while maintaining
        all address mappings and sequence number tracking. Also moves from
        initial CIDs if applicable (inspired by quinn).

        Args:
            cid: Connection ID of the connection to promote
            connection: The QUICConnection instance to register

        """
        async with self._lock:
            # Get sequence number before removal
            sequence = self._cid_sequences.get(cid)

            # Remove from initial CIDs if present
            self._initial_cids.pop(cid, None)
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
                # Maintain reverse mapping for O(1) fallback routing
                self._connection_addresses[connection] = addr

            # Move sequence tracking to connection sequences
            if sequence is not None:
                if connection not in self._connection_sequences:
                    self._connection_sequences[connection] = {}
                self._connection_sequences[connection][sequence] = cid

    async def register_new_cid_for_existing_connection(
        self,
        new_cid: bytes,
        connection: "QUICConnection",
        addr: tuple[str, int],
        sequence: int | None = None,
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
            sequence: Optional sequence number (if known, otherwise will be set later)

        """
        async with self._lock:
            self._connections[new_cid] = connection
            self._cid_to_addr[new_cid] = addr
            # Update addr mapping to use new CID
            self._addr_to_cid[addr] = new_cid

            # Maintain reverse mapping for O(1) fallback routing
            self._connection_addresses[connection] = addr

            # Track sequence if provided
            if sequence is not None:
                self._cid_sequences[new_cid] = sequence
                if connection not in self._connection_sequences:
                    self._connection_sequences[connection] = {}
                self._connection_sequences[connection][sequence] = new_cid

            logger.debug(
                f"Registered new Connection ID {new_cid.hex()[:8]} "
                f"{f'(sequence {sequence}) ' if sequence is not None else ''}"
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
        """Return total number of connections (established + pending + initial)."""
        return len(self._connections) + len(self._pending) + len(self._initial_cids)

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

    async def register_initial_cid(
        self,
        cid: bytes,
        quic_conn: "QuicConnection",
        addr: tuple[str, int],
        sequence: int = 0,
    ) -> None:
        """
        Register an initial destination CID for a pending connection.

        Initial CIDs are used for handshake packets and are tracked separately
        from established connection CIDs (inspired by quinn's architecture).

        Args:
            cid: Initial destination Connection ID
            quic_conn: The aioquic QuicConnection instance
            addr: Remote address (host, port) tuple
            sequence: Sequence number for this Connection ID (default: 0)

        """
        async with self._lock:
            self._initial_cids[cid] = quic_conn
            self._cid_to_addr[cid] = addr
            self._addr_to_cid[addr] = cid
            # Track sequence number
            self._cid_sequences[cid] = sequence

    async def remove_initial_cid(self, cid: bytes) -> None:
        """
        Remove an initial CID and clean up mappings.

        Args:
            cid: Initial Connection ID to remove

        """
        async with self._lock:
            self._initial_cids.pop(cid, None)
            addr = self._cid_to_addr.pop(cid, None)
            if addr:
                if self._addr_to_cid.get(addr) == cid:
                    del self._addr_to_cid[addr]
            # Clean up sequence mapping
            self._cid_sequences.pop(cid, None)

    async def get_sequence_for_cid(self, cid: bytes) -> int | None:
        """
        Get the sequence number for a Connection ID.

        Args:
            cid: Connection ID to look up

        Returns:
            Sequence number if found, None otherwise

        """
        async with self._lock:
            return self._cid_sequences.get(cid)

    async def get_cids_by_sequence_range(
        self, connection: "QUICConnection", start_seq: int, end_seq: int
    ) -> list[bytes]:
        """
        Get Connection IDs for a connection within a sequence number range.

        This is useful for retirement ordering per QUIC specification.

        Args:
            connection: The QUICConnection instance
            start_seq: Start sequence number (inclusive)
            end_seq: End sequence number (exclusive)

        Returns:
            List of Connection IDs in the sequence range

        """
        async with self._lock:
            if connection not in self._connection_sequences:
                return []

            cids = []
            for seq, cid in self._connection_sequences[connection].items():
                if start_seq <= seq < end_seq:
                    cids.append(cid)
            return sorted(cids, key=lambda c: self._cid_sequences.get(c, 0))

    def get_stats(self) -> dict[str, int]:
        """
        Get registry statistics.

        Returns:
            Dictionary with connection counts

        """
        return {
            "initial_connections": len(self._initial_cids),
            "established_connections": len(self._connections),
            "pending_connections": len(self._pending),
            "total_connection_ids": len(self._cid_to_addr),
            "address_mappings": len(self._addr_to_cid),
            "tracked_sequences": len(self._cid_sequences),
        }

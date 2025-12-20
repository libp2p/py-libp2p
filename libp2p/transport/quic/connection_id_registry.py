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

from collections import defaultdict
import logging
import time
from typing import TYPE_CHECKING, Any

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
        # Initial Connection IDs (for handshake packets) - separate from established
        # (inspired by quinn)
        # Maps initial destination Connection ID to pending QuicConnection
        self._initial_connection_ids: dict[bytes, "QuicConnection"] = {}

        # Established connections: Connection ID -> QUICConnection
        self._connections: dict[bytes, "QUICConnection"] = {}

        # Pending connections: Connection ID -> QuicConnection (aioquic)
        self._pending: dict[bytes, "QuicConnection"] = {}

        # Connection ID -> address mapping
        self._connection_id_to_addr: dict[bytes, tuple[str, int]] = {}

        # Address -> Connection ID mapping
        self._addr_to_connection_id: dict[tuple[str, int], bytes] = {}

        # Address -> established connections mapping.
        # Supports multiple connections per address (e.g. tests that reuse addr tuples).
        self._addr_to_connections: defaultdict[
            tuple[str, int], set["QUICConnection"]
        ] = defaultdict(set)

        # Reverse mapping: Connection -> address (for O(1) fallback routing,
        # inspired by quinn)
        self._connection_addresses: dict["QUICConnection", tuple[str, int]] = {}

        # Primary CID and CID counts per connection (avoid scans on cleanup/routing).
        self._connection_primary_cid: dict["QUICConnection", bytes] = {}
        self._connection_cid_counts: dict["QUICConnection", int] = {}

        # Sequence number tracking (inspired by quinn's architecture)
        # Connection ID -> sequence number mapping
        self._connection_id_sequences: dict[bytes, int] = {}
        # Connection -> sequence -> Connection ID mapping (for retirement ordering)
        self._connection_sequences: dict["QUICConnection", dict[int, bytes]] = {}

        # Sequence counter tracking per connection (moved from listener for better
        # encapsulation)
        # Maps connection Connection ID to sequence counter
        # (starts at 0 for initial Connection ID)
        self._connection_sequence_counters: dict[bytes, int] = {}

        # Performance metrics
        self._fallback_routing_count: int = 0
        self._sequence_distribution: dict[int, int] = defaultdict(int)
        self._operation_timings: dict[str, list[float]] = defaultdict(list)
        self._debug_timing: bool = False  # Enable with environment variable

        # Lock contention tracking
        self._lock_stats = {
            "acquisitions": 0,
            "total_wait_time": 0.0,
            "max_wait_time": 0.0,
            "max_hold_time": 0.0,
            "concurrent_holds": 0,
            "current_holds": 0,
        }

        # Lock for thread-safe operations
        self._lock = lock

    async def find_by_connection_id(  # pyrefly: ignore[bad-return]
        self, connection_id: bytes, is_initial: bool = False
    ) -> tuple["QUICConnection | None", "QuicConnection | None", bool]:
        """
        Find connection by QUIC Connection ID.

        Args:
            connection_id: QUIC Connection ID to look up
            is_initial: Whether this is an initial packet
                (checks _initial_connection_ids first)

        Returns:
            Tuple of (established_connection, pending_connection, is_pending)
            - If found in established: (connection, None, False)
            - If found in pending: (None, quic_conn, True)
            - If found in initial: (None, quic_conn, True)
            - If not found: (None, None, False)

        """
        call_start = time.time()

        # Track lock acquisition
        self._lock_stats["acquisitions"] += 1
        was_contended = self._lock_stats["current_holds"] > 0

        async with self._lock:
            self._lock_stats["current_holds"] += 1
            if self._lock_stats["current_holds"] > self._lock_stats["concurrent_holds"]:
                self._lock_stats["concurrent_holds"] = self._lock_stats["current_holds"]

            hold_start = time.time()

            try:
                # For initial packets, check initial Connection IDs first
                # (inspired by quinn)
                if is_initial and connection_id in self._initial_connection_ids:
                    result: tuple[
                        "QUICConnection | None", "QuicConnection | None", bool
                    ] = (
                        None,
                        self._initial_connection_ids[connection_id],
                        True,
                    )
                # Check established connections
                elif connection_id in self._connections:
                    result = (self._connections[connection_id], None, False)
                # Check pending connections
                elif connection_id in self._pending:
                    result = (None, self._pending[connection_id], True)
                else:
                    result = (None, None, False)

                hold_duration = time.time() - hold_start
                total_duration = time.time() - call_start

                # Track max hold time
                if hold_duration > self._lock_stats["max_hold_time"]:
                    self._lock_stats["max_hold_time"] = hold_duration

                # Track total wait time (approximate - time when lock was contended)
                if was_contended:
                    self._lock_stats["total_wait_time"] += total_duration
                    if total_duration > self._lock_stats["max_wait_time"]:
                        self._lock_stats["max_wait_time"] = total_duration

                # Log slow operations (>1ms)
                if total_duration > 0.001:
                    logger.debug(
                        f"Slow find_by_connection_id: {total_duration * 1000:.2f}ms "
                        f"(hold: {hold_duration * 1000:.2f}ms, "
                        f"contended: {was_contended}) "
                        f"for Connection ID {connection_id.hex()[:8]}, "
                        f"is_initial={is_initial}"
                    )

                # Track operation timing
                self._operation_timings["find_by_connection_id"].append(total_duration)

                return result
            finally:
                self._lock_stats["current_holds"] -= 1

        # Unreachable: added to satisfy pyrefly static analysis
        return (None, None, False)  # pragma: no cover

    # Note: pyrefly reports bad-return here, but all code paths do return.
    # The return statements are inside a try/finally block which pyrefly
    # cannot statically verify. This is a false positive.
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
            Tuple of (connection, original_connection_id) or (None, None) if not found

        """
        call_start = time.time()

        # Track lock acquisition
        self._lock_stats["acquisitions"] += 1
        was_contended = self._lock_stats["current_holds"] > 0

        async with self._lock:
            self._lock_stats["current_holds"] += 1
            if self._lock_stats["current_holds"] > self._lock_stats["concurrent_holds"]:
                self._lock_stats["concurrent_holds"] = self._lock_stats["current_holds"]

            hold_start = time.time()

            try:
                # Strategy 1: Try address-to-Connection ID lookup (O(1))
                original_connection_id = self._addr_to_connection_id.get(addr)
                if original_connection_id:
                    connection = self._connections.get(original_connection_id)
                    if connection:
                        hold_duration = time.time() - hold_start
                        total_duration = time.time() - call_start

                        # Track max hold time
                        if hold_duration > self._lock_stats["max_hold_time"]:
                            self._lock_stats["max_hold_time"] = hold_duration

                        # Track total wait time (approximate -
                        # time when lock was contended)
                        if was_contended:
                            self._lock_stats["total_wait_time"] += total_duration
                            if total_duration > self._lock_stats["max_wait_time"]:
                                self._lock_stats["max_wait_time"] = total_duration

                        # Log slow operations (>5ms)
                        if total_duration > 0.005:
                            logger.debug(
                                f"Slow find_by_address (strategy 1): "
                                f"{total_duration * 1000:.2f}ms "
                                f"(hold: {hold_duration * 1000:.2f}ms, "
                                f"contended: {was_contended}) for {addr}"
                            )

                        # Track operation timing
                        self._operation_timings["find_by_address"].append(
                            total_duration
                        )
                        self._fallback_routing_count += 1

                        return (connection, original_connection_id)
                    else:
                        # Address mapping exists but connection not found
                        # Clean up stale mapping
                        del self._addr_to_connection_id[addr]
                        hold_duration = time.time() - hold_start
                        total_duration = time.time() - call_start

                        # Track max hold time
                        if hold_duration > self._lock_stats["max_hold_time"]:
                            self._lock_stats["max_hold_time"] = hold_duration

                        # Track total wait time (approximate -
                        # time when lock was contended)
                        if was_contended:
                            self._lock_stats["total_wait_time"] += total_duration
                            if total_duration > self._lock_stats["max_wait_time"]:
                                self._lock_stats["max_wait_time"] = total_duration

                        # Log slow operations (>5ms)
                        if total_duration > 0.005:
                            logger.debug(
                                f"Slow find_by_address (cleanup): "
                                f"{total_duration * 1000:.2f}ms "
                                f"(hold: {hold_duration * 1000:.2f}ms, "
                                f"contended: {was_contended}) for {addr}"
                            )

                        # Track operation timing
                        self._operation_timings["find_by_address"].append(
                            total_duration
                        )

                        return (None, None)

                # Strategy 2: Try established connection lookup by
                #  address (O(1) average).
                # This avoids scanning all connections on fallback routing.
                connections_at_addr = self._addr_to_connections.get(addr)
                if connections_at_addr:
                    connection = next(iter(connections_at_addr))
                    original_connection_id = self._connection_primary_cid.get(
                        connection
                    )
                    self._fallback_routing_count += 1

                    hold_duration = time.time() - hold_start
                    total_duration = time.time() - call_start

                    # Track max hold time
                    if hold_duration > self._lock_stats["max_hold_time"]:
                        self._lock_stats["max_hold_time"] = hold_duration

                    # Track total wait time (approximate - time when lock was contended)
                    if was_contended:
                        self._lock_stats["total_wait_time"] += total_duration
                        if total_duration > self._lock_stats["max_wait_time"]:
                            self._lock_stats["max_wait_time"] = total_duration

                    # Log slow operations (>5ms)
                    if total_duration > 0.005:
                        logger.debug(
                            f"Slow find_by_address (strategy 2): "
                            f"{total_duration * 1000:.2f}ms "
                            f"(hold: {hold_duration * 1000:.2f}ms, "
                            f"contended: {was_contended}) for {addr}"
                        )

                    # Track operation timing
                    self._operation_timings["find_by_address"].append(total_duration)
                    return (connection, original_connection_id)

                # Not found
                hold_duration = time.time() - hold_start
                total_duration = time.time() - call_start

                # Track max hold time
                if hold_duration > self._lock_stats["max_hold_time"]:
                    self._lock_stats["max_hold_time"] = hold_duration

                # Track total wait time (approximate - time when lock was contended)
                if was_contended:
                    self._lock_stats["total_wait_time"] += total_duration
                    if total_duration > self._lock_stats["max_wait_time"]:
                        self._lock_stats["max_wait_time"] = total_duration

                # Log slow operations (>5ms)
                if total_duration > 0.005:
                    logger.debug(
                        f"Slow find_by_address (not found): "
                        f"{total_duration * 1000:.2f}ms "
                        f"(hold: {hold_duration * 1000:.2f}ms, "
                        f"contended: {was_contended}) for {addr}"
                    )

                # Track operation timing
                self._operation_timings["find_by_address"].append(total_duration)

                return (None, None)
            finally:
                self._lock_stats["current_holds"] -= 1

        # Unreachable: added to satisfy pyrefly static analysis
        return (None, None)  # pragma: no cover

    async def register_connection(
        self,
        connection_id: bytes,
        connection: "QUICConnection",
        addr: tuple[str, int],
        sequence: int = 0,
    ) -> None:
        """
        Register an established connection.

        Args:
            connection_id: Connection ID for this connection
            connection: The QUICConnection instance
            addr: Remote address (host, port) tuple
            sequence: Sequence number for this Connection ID (default: 0)

        """
        call_start = time.time()
        self._lock_stats["acquisitions"] += 1
        was_contended = self._lock_stats["current_holds"] > 0

        async with self._lock:
            self._lock_stats["current_holds"] += 1
            if self._lock_stats["current_holds"] > self._lock_stats["concurrent_holds"]:
                self._lock_stats["concurrent_holds"] = self._lock_stats["current_holds"]

            hold_start = time.time()

            try:
                previous = self._connections.get(connection_id)
                self._connections[connection_id] = connection
                self._connection_id_to_addr[connection_id] = addr
                self._addr_to_connection_id[addr] = connection_id

                # Maintain reverse mapping for O(1) fallback routing
                self._connection_addresses[connection] = addr
                self._addr_to_connections[addr].add(connection)
                self._connection_primary_cid.setdefault(connection, connection_id)
                if previous is not connection:
                    self._connection_cid_counts[connection] = (
                        self._connection_cid_counts.get(connection, 0) + 1
                    )

                # Track sequence number
                self._connection_id_sequences[connection_id] = sequence
                if connection not in self._connection_sequences:
                    self._connection_sequences[connection] = {}
                self._connection_sequences[connection][sequence] = connection_id

                # Track sequence in distribution for performance metrics
                self._sequence_distribution[sequence] += 1

                # Initialize sequence counter if not already set
                if connection_id not in self._connection_sequence_counters:
                    self._connection_sequence_counters[connection_id] = sequence

                hold_duration = time.time() - hold_start
                total_duration = time.time() - call_start

                if hold_duration > self._lock_stats["max_hold_time"]:
                    self._lock_stats["max_hold_time"] = hold_duration

                if was_contended:
                    self._lock_stats["total_wait_time"] += total_duration
                    if total_duration > self._lock_stats["max_wait_time"]:
                        self._lock_stats["max_wait_time"] = total_duration

                if total_duration > 0.005:
                    logger.debug(
                        f"Slow register_connection: {total_duration * 1000:.2f}ms "
                        f"(hold: {hold_duration * 1000:.2f}ms) for Connection ID "
                        f"{connection_id.hex()[:8]}"
                    )

                self._operation_timings["register_connection"].append(total_duration)
            finally:
                self._lock_stats["current_holds"] -= 1

    async def register_pending(
        self,
        connection_id: bytes,
        quic_conn: "QuicConnection",
        addr: tuple[str, int],
        sequence: int = 0,
    ) -> None:
        """
        Register a pending (handshaking) connection.

        Args:
            connection_id: Connection ID for this pending connection
            quic_conn: The aioquic QuicConnection instance
            addr: Remote address (host, port) tuple
            sequence: Sequence number for this Connection ID (default: 0)

        """
        call_start = time.time()
        self._lock_stats["acquisitions"] += 1
        was_contended = self._lock_stats["current_holds"] > 0

        async with self._lock:
            self._lock_stats["current_holds"] += 1
            if self._lock_stats["current_holds"] > self._lock_stats["concurrent_holds"]:
                self._lock_stats["concurrent_holds"] = self._lock_stats["current_holds"]

            hold_start = time.time()

            try:
                self._pending[connection_id] = quic_conn
                self._connection_id_to_addr[connection_id] = addr
                self._addr_to_connection_id[addr] = connection_id

                # Track sequence number (will be moved to connection sequences
                # when promoted)
                self._connection_id_sequences[connection_id] = sequence

                # Initialize sequence counter if not already set
                if connection_id not in self._connection_sequence_counters:
                    self._connection_sequence_counters[connection_id] = sequence

                hold_duration = time.time() - hold_start
                total_duration = time.time() - call_start

                if hold_duration > self._lock_stats["max_hold_time"]:
                    self._lock_stats["max_hold_time"] = hold_duration

                if was_contended:
                    self._lock_stats["total_wait_time"] += total_duration
                    if total_duration > self._lock_stats["max_wait_time"]:
                        self._lock_stats["max_wait_time"] = total_duration

                if total_duration > 0.005:
                    logger.debug(
                        f"Slow register_pending: {total_duration * 1000:.2f}ms "
                        f"(hold: {hold_duration * 1000:.2f}ms) for Connection ID "
                        f"{connection_id.hex()[:8]}"
                    )

                self._operation_timings["register_pending"].append(total_duration)
            finally:
                self._lock_stats["current_holds"] -= 1

    async def add_connection_id(
        self, new_connection_id: bytes, existing_connection_id: bytes, sequence: int
    ) -> None:
        """
        Add a new Connection ID for an existing connection.

        This is called when a ConnectionIdIssued event is received.
        The new Connection ID is mapped to the same address and connection
        as the existing Connection ID.

        Args:
            new_connection_id: New Connection ID to register
            existing_connection_id: Existing Connection ID that's already registered
            sequence: Sequence number for the new Connection ID

        """
        call_start = time.time()
        self._lock_stats["acquisitions"] += 1
        was_contended = self._lock_stats["current_holds"] > 0

        async with self._lock:
            self._lock_stats["current_holds"] += 1
            if self._lock_stats["current_holds"] > self._lock_stats["concurrent_holds"]:
                self._lock_stats["concurrent_holds"] = self._lock_stats["current_holds"]

            hold_start = time.time()

            try:
                # Get address from existing Connection ID
                addr = self._connection_id_to_addr.get(existing_connection_id)
                if not addr:
                    logger.warning(
                        f"Could not find address for existing Connection ID "
                        f"{existing_connection_id.hex()[:8]} when adding "
                        f"new Connection ID "
                        f"{new_connection_id.hex()[:8]}"
                    )
                    return

                # Map new Connection ID to the same address
                self._connection_id_to_addr[new_connection_id] = addr

                # Track sequence number
                self._connection_id_sequences[new_connection_id] = sequence
                # Update sequence distribution
                self._sequence_distribution[sequence] += 1

                # If connection is already promoted, also map new Connection ID
                # to the connection
                if existing_connection_id in self._connections:
                    connection = self._connections[existing_connection_id]
                    previous = self._connections.get(new_connection_id)
                    self._connections[new_connection_id] = connection
                    if previous is not connection:
                        self._connection_cid_counts[connection] = (
                            self._connection_cid_counts.get(connection, 0) + 1
                        )

                    # Track sequence for this connection
                    if connection not in self._connection_sequences:
                        self._connection_sequences[connection] = {}
                    self._connection_sequences[connection][sequence] = new_connection_id

                    logger.debug(
                        f"Registered new Connection ID {new_connection_id.hex()[:8]} "
                        f"(sequence {sequence}) for existing connection "
                        f"{existing_connection_id.hex()[:8]} at address {addr}"
                    )

                hold_duration = time.time() - hold_start
                total_duration = time.time() - call_start

                if hold_duration > self._lock_stats["max_hold_time"]:
                    self._lock_stats["max_hold_time"] = hold_duration

                if was_contended:
                    self._lock_stats["total_wait_time"] += total_duration
                    if total_duration > self._lock_stats["max_wait_time"]:
                        self._lock_stats["max_wait_time"] = total_duration

                if total_duration > 0.005:
                    logger.debug(
                        f"Slow add_connection_id: {total_duration * 1000:.2f}ms "
                        f"(hold: {hold_duration * 1000:.2f}ms) "
                        f"for Connection ID {new_connection_id.hex()[:8]}"
                    )

                self._operation_timings["add_connection_id"].append(total_duration)
            finally:
                self._lock_stats["current_holds"] -= 1

    async def remove_connection_id(
        self, connection_id: bytes
    ) -> tuple[str, int] | None:
        """
        Remove a Connection ID and clean up all related mappings.

        Args:
            connection_id: Connection ID to remove

        Returns:
            The address that was associated with this Connection ID, or None

        """
        call_start = time.time()
        self._lock_stats["acquisitions"] += 1
        was_contended = self._lock_stats["current_holds"] > 0

        async with self._lock:
            self._lock_stats["current_holds"] += 1
            if self._lock_stats["current_holds"] > self._lock_stats["concurrent_holds"]:
                self._lock_stats["concurrent_holds"] = self._lock_stats["current_holds"]

            hold_start = time.time()

            try:
                # Get connection and sequence before removal
                connection = self._connections.get(connection_id)
                sequence = self._connection_id_sequences.get(connection_id)
                primary_before = (
                    self._connection_primary_cid.get(connection) if connection else None
                )

                # Remove from initial, established, and pending
                self._initial_connection_ids.pop(connection_id, None)
                self._connections.pop(connection_id, None)
                self._pending.pop(connection_id, None)

                # Get and remove address mapping
                addr = self._connection_id_to_addr.pop(connection_id, None)
                if addr:
                    # If this was the active CID for the address, repoint to another
                    # CID for the same connection if possible.
                    if self._addr_to_connection_id.get(addr) == connection_id:
                        replacement: bytes | None = None
                        if connection and connection in self._connection_sequences:
                            # Prefer lowest remaining sequence for determinism
                            seq_map = self._connection_sequences[connection]
                            if seq_map:
                                candidate_seqs = [
                                    s
                                    for s, cid in seq_map.items()
                                    if cid != connection_id
                                ]
                                if candidate_seqs:
                                    replacement = seq_map[min(candidate_seqs)]
                        if replacement is not None:
                            self._addr_to_connection_id[addr] = replacement
                        else:
                            self._addr_to_connection_id.pop(addr, None)

                # Clean up sequence mappings
                if sequence is not None:
                    self._connection_id_sequences.pop(connection_id, None)
                    if connection and connection in self._connection_sequences:
                        self._connection_sequences[connection].pop(sequence, None)
                        # Clean up empty connection sequences dict
                        if not self._connection_sequences[connection]:
                            del self._connection_sequences[connection]

                if connection:
                    # If we removed the primary CID, repoint it if other CIDs remain.
                    if primary_before == connection_id:
                        replacement_primary: bytes | None = None
                        if connection in self._connection_sequences:
                            seq_map = self._connection_sequences[connection]
                            if seq_map:
                                candidate_seqs = [
                                    s
                                    for s, cid in seq_map.items()
                                    if cid != connection_id
                                ]
                                if candidate_seqs:
                                    replacement_primary = seq_map[min(candidate_seqs)]
                        if replacement_primary is not None:
                            self._connection_primary_cid[connection] = (
                                replacement_primary
                            )
                        else:
                            self._connection_primary_cid.pop(connection, None)

                    # Decrement CID count and cleanup per-connection mappings if this
                    # was the last tracked CID.
                    current = self._connection_cid_counts.get(connection, 0)
                    if current > 0:
                        new_count = current - 1
                        if new_count <= 0:
                            self._connection_cid_counts.pop(connection, None)
                            self._connection_primary_cid.pop(connection, None)
                            conn_addr = self._connection_addresses.pop(connection, None)
                            if conn_addr:
                                conns = self._addr_to_connections.get(conn_addr)
                                if conns:
                                    conns.discard(connection)
                                    if not conns:
                                        self._addr_to_connections.pop(conn_addr, None)
                        else:
                            self._connection_cid_counts[connection] = new_count
                    # Clean up sequence counter for this Connection ID
                    self._connection_sequence_counters.pop(connection_id, None)

                hold_duration = time.time() - hold_start
                total_duration = time.time() - call_start

                if hold_duration > self._lock_stats["max_hold_time"]:
                    self._lock_stats["max_hold_time"] = hold_duration

                if was_contended:
                    self._lock_stats["total_wait_time"] += total_duration
                    if total_duration > self._lock_stats["max_wait_time"]:
                        self._lock_stats["max_wait_time"] = total_duration

                if total_duration > 0.005:
                    logger.debug(
                        f"Slow remove_connection_id: {total_duration * 1000:.2f}ms "
                        f"(hold: {hold_duration * 1000:.2f}ms) for Connection ID "
                        f"{connection_id.hex()[:8]}"
                    )

                self._operation_timings["remove_connection_id"].append(total_duration)

                return addr
            finally:
                self._lock_stats["current_holds"] -= 1

    async def remove_pending_connection(self, connection_id: bytes) -> None:
        """
        Remove a pending connection and clean up mappings.

        Args:
            connection_id: Connection ID of pending connection to remove

        """
        async with self._lock:
            self._pending.pop(connection_id, None)
            addr = self._connection_id_to_addr.pop(connection_id, None)
            if addr:
                if self._addr_to_connection_id.get(addr) == connection_id:
                    del self._addr_to_connection_id[addr]

            # Clean up sequence mapping
            self._connection_id_sequences.pop(connection_id, None)

    async def remove_by_address(self, addr: tuple[str, int]) -> bytes | None:
        """
        Remove connection by address.

        Args:
            addr: Remote address (host, port) tuple

        Returns:
            The Connection ID that was associated with this address, or None

        """
        async with self._lock:
            connection_id = self._addr_to_connection_id.pop(addr, None)
            if connection_id:
                connection = self._connections.get(connection_id)
                self._initial_connection_ids.pop(connection_id, None)
                self._connections.pop(connection_id, None)
                self._pending.pop(connection_id, None)
                self._connection_id_to_addr.pop(connection_id, None)
                self._connection_id_sequences.pop(connection_id, None)
                self._connection_sequence_counters.pop(connection_id, None)
                # Clean up reverse mapping
                if connection:
                    # Remove from address->connections set
                    conns = self._addr_to_connections.get(addr)
                    if conns:
                        conns.discard(connection)
                        if not conns:
                            self._addr_to_connections.pop(addr, None)

                    # Remove per-connection mappings.
                    self._connection_addresses.pop(connection, None)
                    self._connection_primary_cid.pop(connection, None)
                    self._connection_cid_counts.pop(connection, None)
                    self._connection_sequences.pop(connection, None)
            return connection_id

    async def promote_pending(
        self, connection_id: bytes, connection: "QUICConnection"
    ) -> None:
        """
        Promote a pending connection to established.

        Moves the connection from pending to established while maintaining
        all address mappings and sequence number tracking. Also moves from
        initial Connection IDs if applicable (inspired by quinn).

        Args:
            connection_id: Connection ID of the connection to promote
            connection: The QUICConnection instance to register

        """
        async with self._lock:
            # Get sequence number before removal
            sequence = self._connection_id_sequences.get(connection_id)

            # Remove from initial Connection IDs if present
            self._initial_connection_ids.pop(connection_id, None)
            # Remove from pending
            self._pending.pop(connection_id, None)

            # Add to established (may already exist, that's OK)
            if connection_id in self._connections:
                logger.warning(
                    f"Connection {connection_id.hex()[:8]} already exists in "
                    f"_connections! Reusing existing connection."
                )
            else:
                self._connections[connection_id] = connection
                self._connection_cid_counts[connection] = (
                    self._connection_cid_counts.get(connection, 0) + 1
                )
                self._connection_primary_cid.setdefault(connection, connection_id)

            # Ensure address mappings are up to date
            # (they should already exist from when pending was registered)
            if connection_id in self._connection_id_to_addr:
                addr = self._connection_id_to_addr[connection_id]
                self._addr_to_connection_id[addr] = connection_id
                # Maintain reverse mapping for O(1) fallback routing
                self._connection_addresses[connection] = addr
                self._addr_to_connections[addr].add(connection)

            # Move sequence tracking to connection sequences
            if sequence is not None:
                if connection not in self._connection_sequences:
                    self._connection_sequences[connection] = {}
                self._connection_sequences[connection][sequence] = connection_id

    async def register_new_connection_id_for_existing_conn(
        self,
        new_connection_id: bytes,
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
            new_connection_id: New Connection ID to register
            connection: The existing QUICConnection instance
            addr: Remote address (host, port) tuple
            sequence: Optional sequence number (if known, otherwise will be set later)

        """
        async with self._lock:
            previous = self._connections.get(new_connection_id)
            self._connections[new_connection_id] = connection
            self._connection_id_to_addr[new_connection_id] = addr
            # Update addr mapping to use new Connection ID
            self._addr_to_connection_id[addr] = new_connection_id

            # Maintain reverse mapping for O(1) fallback routing
            self._connection_addresses[connection] = addr
            self._addr_to_connections[addr].add(connection)
            self._connection_primary_cid.setdefault(connection, new_connection_id)
            if previous is not connection:
                self._connection_cid_counts[connection] = (
                    self._connection_cid_counts.get(connection, 0) + 1
                )

            # Track sequence if provided
            if sequence is not None:
                self._connection_id_sequences[new_connection_id] = sequence
                if connection not in self._connection_sequences:
                    self._connection_sequences[connection] = {}
                self._connection_sequences[connection][sequence] = new_connection_id

            logger.debug(
                f"Registered new Connection ID {new_connection_id.hex()[:8]} "
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
            for connection_id, conn in self._connections.items():
                if conn is connection:
                    cids.append(connection_id)
            return cids

    async def cleanup_stale_address_mapping(self, addr: tuple[str, int]) -> None:
        """
        Clean up a stale address mapping.

        Used when address mapping exists but connection is not found.

        Args:
            addr: Address to clean up

        """
        async with self._lock:
            self._addr_to_connection_id.pop(addr, None)

    def __len__(self) -> int:
        """Return total number of connections (established + pending + initial)."""
        return (
            len(self._connections)
            + len(self._pending)
            + len(self._initial_connection_ids)
        )

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

    async def register_initial_connection_id(
        self,
        connection_id: bytes,
        quic_conn: "QuicConnection",
        addr: tuple[str, int],
        sequence: int = 0,
    ) -> None:
        """
        Register an initial destination Connection ID for a pending connection.

        Initial Connection IDs are used for handshake packets and are tracked separately
        from established connection Connection IDs (inspired by quinn's architecture).

        Args:
            connection_id: Initial destination Connection ID
            quic_conn: The aioquic QuicConnection instance
            addr: Remote address (host, port) tuple
            sequence: Sequence number for this Connection ID (default: 0)

        """
        async with self._lock:
            self._initial_connection_ids[connection_id] = quic_conn
            self._connection_id_to_addr[connection_id] = addr
            self._addr_to_connection_id[addr] = connection_id
            # Track sequence number
            self._connection_id_sequences[connection_id] = sequence

    async def remove_initial_connection_id(self, connection_id: bytes) -> None:
        """
        Remove an initial Connection ID and clean up mappings.

        Args:
            connection_id: Initial Connection ID to remove

        """
        async with self._lock:
            self._initial_connection_ids.pop(connection_id, None)
            addr = self._connection_id_to_addr.pop(connection_id, None)
            if addr:
                if self._addr_to_connection_id.get(addr) == connection_id:
                    del self._addr_to_connection_id[addr]
            # Clean up sequence mapping
            self._connection_id_sequences.pop(connection_id, None)

    async def get_sequence_for_connection_id(self, connection_id: bytes) -> int | None:
        """
        Get the sequence number for a Connection ID.

        Args:
            connection_id: Connection ID to look up

        Returns:
            Sequence number if found, None otherwise

        """
        async with self._lock:
            return self._connection_id_sequences.get(connection_id)

    async def get_sequence_counter(self, connection_id: bytes) -> int:
        """
        Get the sequence counter for a connection (by its Connection ID).

        Args:
            connection_id: Connection ID to look up

        Returns:
            Current sequence counter value (defaults to 0 if not found)

        """
        async with self._lock:
            return self._connection_sequence_counters.get(connection_id, 0)

    async def increment_sequence_counter(self, connection_id: bytes) -> int:
        """
        Increment the sequence counter for a connection and return the new value.

        Args:
            connection_id: Connection ID to increment counter for

        Returns:
            New sequence counter value

        """
        async with self._lock:
            current = self._connection_sequence_counters.get(connection_id, 0)
            new_value = current + 1
            self._connection_sequence_counters[connection_id] = new_value
            return new_value

    async def set_sequence_counter(self, connection_id: bytes, value: int) -> None:
        """
        Set the sequence counter for a connection.

        Args:
            connection_id: Connection ID to set counter for
            value: Sequence counter value to set

        """
        async with self._lock:
            self._connection_sequence_counters[connection_id] = value

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
            List of Connection IDs in the sequence range, sorted by sequence number

        """
        async with self._lock:
            if connection not in self._connection_sequences:
                return []

            connection_ids = []
            for seq, connection_id in self._connection_sequences[connection].items():
                if start_seq <= seq < end_seq:
                    connection_ids.append(connection_id)
            return sorted(
                connection_ids,
                key=lambda c: self._connection_id_sequences.get(c, 0),
            )

    async def retire_connection_ids_by_sequence_range(
        self, connection: "QUICConnection", start_seq: int, end_seq: int
    ) -> list[bytes]:
        """
        Retire Connection IDs for a connection within a sequence number range.

        This implements proper retirement ordering per QUIC specification by
        retiring CIDs in sequence order.

        Args:
            connection: The QUICConnection instance
            start_seq: Start sequence number (inclusive)
            end_seq: End sequence number (exclusive)

        Returns:
            List of retired Connection IDs

        """
        # Get CIDs in sequence order (this acquires the lock)
        cids_to_retire = await self.get_cids_by_sequence_range(
            connection, start_seq, end_seq
        )

        # Remove each CID in sequence order (each call acquires the lock)
        retired = []
        for connection_id in cids_to_retire:
            addr = await self.remove_connection_id(connection_id)
            if addr:
                retired.append(connection_id)
                seq = await self.get_sequence_for_connection_id(connection_id)
                logger.debug(
                    f"Retired Connection ID {connection_id.hex()[:8]} "
                    f"(sequence {seq}) for connection"
                )

        return retired

    def get_lock_stats(self) -> dict[str, float | int]:
        """
        Get lock contention statistics.

        Returns:
            Dictionary with lock statistics including acquisitions,
            wait times, and hold times

        """
        acquisitions = self._lock_stats["acquisitions"]
        avg_wait_time = (
            self._lock_stats["total_wait_time"] / acquisitions
            if acquisitions > 0
            else 0.0
        )

        return {
            "acquisitions": acquisitions,
            "total_wait_time": self._lock_stats["total_wait_time"],
            "avg_wait_time": avg_wait_time,
            "max_wait_time": self._lock_stats["max_wait_time"],
            "max_hold_time": self._lock_stats["max_hold_time"],
            "max_concurrent_holds": self._lock_stats["concurrent_holds"],
            "current_holds": self._lock_stats["current_holds"],
        }

    def get_stats(self) -> dict[str, int | dict[str, Any]]:
        """
        Get registry statistics.

        Returns:
            Dictionary with connection counts and performance metrics

        """
        stats: dict[str, int | dict[str, Any]] = {
            "initial_connections": len(self._initial_connection_ids),
            "established_connections": len(self._connections),
            "pending_connections": len(self._pending),
            "total_connection_ids": len(self._connection_id_to_addr),
            "address_mappings": len(self._addr_to_connection_id),
            "tracked_sequences": len(self._connection_id_sequences),
            "fallback_routing_count": self._fallback_routing_count,
            "sequence_distribution": dict(self._sequence_distribution),  # type: ignore
            "lock_stats": self.get_lock_stats(),
        }
        if self._debug_timing and self._operation_timings:
            # Calculate average timings
            avg_timings: dict[str, float] = {
                op: sum(times) / len(times) if times else 0.0
                for op, times in self._operation_timings.items()
            }
            stats["operation_timings"] = avg_timings  # type: ignore[assignment]
        return stats

    def reset_stats(self) -> None:
        """Reset performance metrics."""
        self._fallback_routing_count = 0
        self._sequence_distribution.clear()
        self._operation_timings.clear()

"""
Connection pruner implementation for managing connection limits.

This module provides connection pruning functionality that selects connections
to close when connection limits are exceeded, matching go-libp2p behavior.

Reference: https://github.com/libp2p/go-libp2p/blob/master/p2p/net/connmgr/connmgr.go
"""

import logging
from typing import TYPE_CHECKING, Any

from multiaddr import Multiaddr

from libp2p.abc import INetConn, IPeerStore
from libp2p.peer.id import ID
from libp2p.rcmgr import Direction

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm
    from libp2p.network.tag_store import TagStore
import time

logger = logging.getLogger("libp2p.network.connection_pruner")


def get_peer_tag_value(
    peer_store: IPeerStore, peer_id: ID, tag_store: "TagStore | None" = None
) -> int:
    """
    Calculate peer tag value by summing all tag values.

    Uses TagStore if available, otherwise falls back to metadata-based lookup.

    Parameters
    ----------
    peer_store : IPeerStore
        Peer store to query
    peer_id : ID
        Peer ID to check
    tag_store : TagStore | None
        Optional TagStore for proper tag lookups

    Returns
    -------
    int
        Sum of all tag values (0 if no tags or peer not found)

    """
    # Prefer TagStore if available
    if tag_store is not None:
        return tag_store.get_tag_value(peer_id)

    # Fallback to metadata-based lookup for backward compatibility
    try:
        # Access peer_data_map - it exists on PeerStore implementation
        peer_data_map = peer_store.peer_data_map  # type: ignore[attr-defined]
        if peer_data_map is None:
            return 0
        peer_data = peer_data_map.get(peer_id)
        if peer_data is None:
            return 0

        # Check metadata for tag-like values
        if hasattr(peer_data, "metadata") and peer_data.metadata:
            tag_value = 0
            for key, value in peer_data.metadata.items():
                if isinstance(key, str) and key.startswith("tag_"):
                    if isinstance(value, (int, float)):
                        tag_value += int(value)
                    elif isinstance(value, dict) and "value" in value:
                        tag_value += int(value.get("value", 0))

            return tag_value

        return 0
    except AttributeError:
        return 0
    except Exception as e:
        logger.debug("Error getting peer tag value for %s: %s", peer_id, e)
        return 0


def get_connection_direction(connection: INetConn) -> Direction:
    """
    Get the direction of a connection.

    Parameters
    ----------
    connection : INetConn
        The connection to check

    Returns
    -------
    Direction
        INBOUND, OUTBOUND, or UNKNOWN

    """
    try:
        direction = getattr(connection, "direction", None)
        if direction is None:
            direction = getattr(connection, "_direction", None)
        if isinstance(direction, Direction):
            return direction
        elif isinstance(direction, str):
            return Direction.from_string(direction)
        return Direction.UNKNOWN
    except Exception:
        return Direction.UNKNOWN


def is_connection_in_allow_list(connection: INetConn, swarm: "Swarm") -> bool:
    """
    Check if connection is in the allow list.

    Uses ConnectionGate to check if connection's IP is in allow list.
    ConnectionGate is a required attribute of Swarm.

    Parameters
    ----------
    connection : INetConn
        Connection to check
    swarm : Swarm
        Swarm instance to access connection gate

    Returns
    -------
    bool
        True if connection is in allow list, False otherwise

    """
    try:
        # muxed_conn is a required attribute of INetConn interface
        peer_id = connection.muxed_conn.peer_id
        # Get peer addresses from peerstore
        peer_addrs = swarm.peerstore.addrs(peer_id)
        # Check if any peer address is in allow list
        # connection_gate is a required attribute of Swarm
        for addr in peer_addrs:
            if swarm.connection_gate.is_in_allow_list(addr):
                return True
    except Exception as e:
        logger.debug("Error checking allow list for connection: %s", e)
        return False

    return False


class ConnectionPruner:
    """
    Connection pruner that selects connections to close when limits are exceeded.

    Sorts connections by multiple criteria to determine which connections
    should be closed first when the connection limit is exceeded.
    """

    def __init__(
        self, swarm: "Swarm", allow_list: list[str] | list[Multiaddr] | None = None
    ):
        """
        Initialize connection pruner.

        Parameters
        ----------
        swarm : Swarm
            The swarm instance
        allow_list : list[str] | list[Multiaddr] | None
            List of IP addresses/CIDR blocks (str) or multiaddrs that should
            never be pruned (deprecated, now uses ConnectionGate)

        """
        self.swarm = swarm
        # Keep for backward compatibility but use ConnectionGate instead
        # Store as-is (type doesn't matter since it's unused)
        if allow_list is None:
            self.allow_list: list[str] | list[Multiaddr] = []
        else:
            self.allow_list = allow_list
        self._started = False

    async def start(self) -> None:
        """Start the connection pruner."""
        self._started = True

    async def stop(self) -> None:
        """Stop the connection pruner."""
        self._started = False

    async def maybe_prune_connections(self) -> None:
        """
        Check if connections need to be pruned and prune if necessary.

        Triggered when a new connection is opened or periodically.
        Uses high_watermark as the trigger point for pruning.
        """
        if not self._started:
            return

        try:
            await self._maybe_prune_connections()
        except Exception as e:
            logger.error("Error while pruning connections: %s", e, exc_info=True)

    async def _maybe_prune_connections(self) -> None:
        """Internal method to prune connections if needed."""
        connections = self.swarm.get_connections()
        num_connections = len(connections)
        high_watermark = self.swarm.connection_config.high_watermark
        low_watermark = self.swarm.connection_config.low_watermark

        logger.debug(
            "Checking connections: %d (low=%d, high=%d)",
            num_connections,
            low_watermark,
            high_watermark,
        )

        # Only prune if we're above high watermark
        if num_connections <= high_watermark:
            return

        grace_period = self.swarm.connection_config.grace_period

        # Calculate peer values (sum of tag values)
        peer_values: dict[ID, int] = {}
        for connection in connections:
            try:
                # muxed_conn is a required attribute of INetConn interface
                peer_id = connection.muxed_conn.peer_id
                if peer_id not in peer_values:
                    # Get tag store from swarm if available
                    tag_store = getattr(self.swarm, "tag_store", None)
                    peer_values[peer_id] = get_peer_tag_value(
                        self.swarm.peerstore, peer_id, tag_store
                    )
            except Exception as e:
                logger.debug("Error getting peer_id from connection: %s", e)
                continue

        # Sort connections for pruning
        sorted_connections = self.sort_connections(connections, peer_values)

        # Prune down to low_watermark (not high_watermark)
        # This avoids thrashing between high and low watermark
        to_prune = max(num_connections - low_watermark, 0)
        to_close: list[INetConn] = []

        for connection in sorted_connections:
            try:
                conn_peer_id = connection.muxed_conn.peer_id
                logger.debug(
                    "Too many connections open - considering connection to peer %s",
                    conn_peer_id,
                )
            except Exception:
                logger.debug(
                    "Too many connections open - considering connection "
                    "with unknown peer"
                )
                conn_peer_id = None

            # Respect ConnectionConfig.grace_period: skip recently established
            # connections. Connections without _created_at are skipped (safe default).
            if self._is_connection_within_grace_period(connection, grace_period):
                logger.debug(
                    "Skipping connection to %s - within grace period",
                    conn_peer_id,
                )
                continue

            # Check if peer is protected
            tag_store = getattr(self.swarm, "tag_store", None)
            if tag_store is not None and conn_peer_id is not None:
                if tag_store.is_protected(conn_peer_id):
                    logger.debug("Skipping protected peer %s", conn_peer_id)
                    continue

            # Check allow list (connections in allow list are never pruned)
            if is_connection_in_allow_list(connection, self.swarm):
                continue

            to_close.append(connection)

            if len(to_close) >= to_prune:
                break

        # Close selected connections
        if to_close:
            logger.info("Pruning %d connections", len(to_close))
            for connection in to_close:
                try:
                    await connection.close()
                except Exception as e:
                    logger.warning("Error closing connection during pruning: %s", e)

    def _is_connection_within_grace_period(
        self, connection: INetConn, grace_period: float
    ) -> bool:
        """
        Return True if this connection should not be pruned due to grace period.

        Connections without _created_at (e.g. non-SwarmConn) are treated as
        within grace period (not pruned) as a safe default.
        """
        try:
            created_at = getattr(connection, "_created_at", None)
        except (AttributeError, TypeError):
            return True
        if created_at is None or not isinstance(created_at, (int, float)):
            return True
        try:
            age = time.time() - float(created_at)
            return age < grace_period
        except (TypeError, ValueError):
            return True

    def sort_connections(
        self, connections: list[INetConn], peer_values: dict[ID, int]
    ) -> list[INetConn]:
        """
        Sort connections for pruning priority.

        Connections are sorted by (in order):
        1. Peer tag value (lowest first)
        2. Stream count (lowest first)
        3. Direction (inbound first, then outbound) - TODO: when direction is available
        4. Connection age (oldest first)

        Parameters
        ----------
        connections : list[INetConn]
            List of connections to sort
        peer_values : dict[ID, int]
            Mapping of peer IDs to their tag values

        Returns
        -------
        list[INetConn]
            Sorted list of connections (first = lowest priority, should be pruned first)

        """
        # Get connection metadata for sorting
        connection_data = []
        for conn in connections:
            try:
                # muxed_conn is a required attribute of INetConn interface
                peer_id = conn.muxed_conn.peer_id
            except Exception:
                peer_id = None

            # Get stream count
            # get_streams() is a required method of INetConn interface
            stream_count = 0
            try:
                streams = conn.get_streams()
                stream_count = len(streams) if streams else 0
            except Exception:
                # Fallback: try to access streams attribute if available
                # (SwarmConn specific)
                try:
                    streams_attr = conn.streams  # type: ignore[attr-defined]
                    if isinstance(streams_attr, (list, set, tuple)):
                        stream_count = len(streams_attr)
                except AttributeError:
                    pass

            # Get connection age (use creation time if available, otherwise 0)
            # _created_at is a SwarmConn-specific attribute, not in the interface
            connection_age = 0.0
            try:
                # Try to get from connection (SwarmConn has this)
                created_at = conn._created_at  # type: ignore[attr-defined]
                if isinstance(created_at, (int, float)):
                    connection_age = float(created_at)
            except AttributeError:
                # Fallback: try to get from muxed connection
                try:
                    muxed_created_at = conn.muxed_conn._created_at  # type: ignore[attr-defined]
                    if isinstance(muxed_created_at, (int, float)):
                        connection_age = float(muxed_created_at)
                except AttributeError:
                    pass

            # Get peer value
            peer_value = peer_values.get(peer_id, 0) if peer_id else 0

            # Get direction (inbound = 0, outbound = 1 for sorting)
            # Inbound connections are pruned first as they were not initiated by us
            direction = get_connection_direction(conn)
            dir_value = direction.value if direction != Direction.UNKNOWN else 0
            direction_sort_value = dir_value

            connection_data.append(
                {
                    "conn": conn,
                    "peer_value": peer_value,
                    "stream_count": stream_count,
                    "direction": direction_sort_value,
                    "age": connection_age,
                }
            )

        # Sort by multiple criteria (stable sort, reverse order for each sort)
        # Helper functions to safely get numeric values
        def get_float_val(item_dict: dict[str, Any], key: str) -> float:
            val = item_dict.get(key, 0)
            if isinstance(val, (int, float)):
                return float(val)
            return 0.0

        def get_int_val(item_dict: dict[str, Any], key: str) -> int:
            val = item_dict.get(key, 0)
            if isinstance(val, (int, float)):
                return int(val)
            return 0

        # Pre-compute sort keys to avoid type issues
        # 1. Sort by connection age (oldest first)
        for item in connection_data:
            item["_sort_age"] = get_float_val(item, "age")

        def get_sort_age(x: dict[str, Any]) -> float:
            val = x.get("_sort_age", 0.0)
            if isinstance(val, (int, float)):
                return float(val)
            return 0.0

        connection_data.sort(key=get_sort_age)

        # 2. Sort by direction (inbound first, then outbound)
        for item in connection_data:
            item["_sort_direction"] = get_int_val(item, "direction")

        def get_sort_direction(x: dict[str, Any]) -> int:
            val = x.get("_sort_direction", 0)
            if isinstance(val, (int, float)):
                return int(val)
            return 0

        connection_data.sort(key=get_sort_direction)

        # 3. Sort by stream count (lowest first)
        for item in connection_data:
            item["_sort_streams"] = get_int_val(item, "stream_count")

        def get_sort_streams(x: dict[str, Any]) -> int:
            val = x.get("_sort_streams", 0)
            if isinstance(val, (int, float)):
                return int(val)
            return 0

        connection_data.sort(key=get_sort_streams)

        # 4. Sort by peer tag value (lowest first) - most important
        for item in connection_data:
            item["_sort_peer_value"] = get_int_val(item, "peer_value")

        def get_sort_peer_value(x: dict[str, Any]) -> int:
            val = x.get("_sort_peer_value", 0)
            if isinstance(val, (int, float)):
                return int(val)
            return 0

        connection_data.sort(key=get_sort_peer_value)

        # Extract connections - we know they're INetConn from construction
        return [item["conn"] for item in connection_data]  # type: ignore[misc]

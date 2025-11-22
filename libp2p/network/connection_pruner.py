"""
Connection pruner implementation for managing connection limits.

This module provides connection pruning functionality that selects connections
to close when connection limits are exceeded, matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/connection-pruner.ts
"""

import logging
from typing import TYPE_CHECKING, Any

from multiaddr import Multiaddr

from libp2p.abc import INetConn, IPeerStore
from libp2p.peer.id import ID

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.network.connection_pruner")


def get_peer_tag_value(peer_store: IPeerStore, peer_id: ID) -> int:
    """
    Calculate peer tag value by summing all tag values.

    Parameters
    ----------
    peer_store : IPeerStore
        Peer store to query
    peer_id : ID
        Peer ID to check

    Returns
    -------
    int
        Sum of all tag values (0 if no tags or peer not found)

    """
    try:
        # Access peer_data_map - it exists on PeerStore implementation
        # Use try/except instead of getattr for better error handling
        peer_data_map = peer_store.peer_data_map  # type: ignore[attr-defined]
        if peer_data_map is None:
            return 0
        peer_data = peer_data_map.get(peer_id)
        if peer_data is None:
            return 0

        # TODO: Replace with proper tags support when peer tags are implemented
        # For now, check metadata for tag-like values
        # metadata is a common attribute on peer data
        if hasattr(peer_data, "metadata") and peer_data.metadata:
            tag_value = 0
            # Look for metadata keys that might represent tags
            # For now, we'll sum any numeric metadata values as a proxy
            for key, value in peer_data.metadata.items():
                if isinstance(key, str) and key.startswith("tag_"):
                    # Extract tag value if stored as metadata
                    if isinstance(value, (int, float)):
                        tag_value += int(value)
                    elif isinstance(value, dict) and "value" in value:
                        tag_value += int(value.get("value", 0))

            return tag_value

        return 0
    except AttributeError:
        # peer_data_map might not exist on all peer store implementations
        return 0
    except Exception as e:
        logger.debug(f"Error getting peer tag value for {peer_id}: {e}")
        return 0


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
        logger.debug(f"Error checking allow list for connection: {e}")
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
        """
        if not self._started:
            return

        try:
            await self._maybe_prune_connections()
        except Exception as e:
            logger.error(f"Error while pruning connections: {e}", exc_info=e)

    async def _maybe_prune_connections(self) -> None:
        """Internal method to prune connections if needed."""
        connections = self.swarm.get_connections()
        num_connections = len(connections)
        max_connections = self.swarm.connection_config.max_connections

        logger.debug(
            f"Checking max connections limit {num_connections}/{max_connections}"
        )

        if num_connections <= max_connections:
            return

        # Calculate peer values (sum of tag values)
        peer_values: dict[ID, int] = {}
        for connection in connections:
            try:
                # muxed_conn is a required attribute of INetConn interface
                peer_id = connection.muxed_conn.peer_id
                if peer_id not in peer_values:
                    peer_values[peer_id] = get_peer_tag_value(
                        self.swarm.peerstore, peer_id
                    )
            except Exception as e:
                logger.debug(f"Error getting peer_id from connection: {e}")
                continue

        # Sort connections for pruning
        sorted_connections = self.sort_connections(connections, peer_values)

        # Determine how many to prune
        to_prune = max(num_connections - max_connections, 0)
        to_close: list[INetConn] = []

        for connection in sorted_connections:
            try:
                peer_id = connection.muxed_conn.peer_id
                logger.debug(
                    f"Too many connections open - considering connection "
                    f"to peer {peer_id}"
                )
            except Exception:
                logger.debug(
                    "Too many connections open - considering connection "
                    "with unknown peer"
                )

            # Check allow list (connections in allow list are never pruned)
            if is_connection_in_allow_list(connection, self.swarm):
                continue

            to_close.append(connection)

            if len(to_close) >= to_prune:
                break

        # Close selected connections
        if to_close:
            logger.info(f"Pruning {len(to_close)} connections")
            for connection in to_close:
                try:
                    # Close connection gracefully
                    await connection.close()
                except Exception as e:
                    logger.warning(f"Error closing connection during pruning: {e}")

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

            # Direction (inbound = 0, outbound = 1 for sorting)
            # TODO: Get actual direction when available
            direction = 0  # Default to inbound for sorting

            connection_data.append(
                {
                    "conn": conn,
                    "peer_value": peer_value,
                    "stream_count": stream_count,
                    "direction": direction,
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

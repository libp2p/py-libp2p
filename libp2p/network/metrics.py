"""
Connection metrics tracking for libp2p.

This module provides metrics tracking for connection management,
matching the JavaScript libp2p connection manager metrics.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/index.ts
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from libp2p.abc import INetConn, INetStream
    from libp2p.peer.id import ID
else:
    # Runtime imports for type annotations
    from libp2p.abc import INetConn, INetStream
    from libp2p.peer.id import ID


@dataclass
class ConnectionMetrics:
    """
    Metrics for connection management.

    Tracks connection counts, pending connections, and protocol stream statistics.
    All metrics are calculated on-demand to match JS libp2p behavior.
    """

    # Connection counts
    inbound_connections: int = 0
    outbound_connections: int = 0
    inbound_pending: int = 0
    outbound_pending: int = 0

    # Protocol stream counts (direction + protocol -> count)
    protocol_streams: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Stream counts per connection per protocol (for percentile calculation)
    # Format: protocol -> list of stream counts per connection
    _protocol_stream_counts: dict[str, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def update_connection_counts(
        self,
        connections: dict[ID, list[INetConn]],
        inbound_pending: int = 0,
        outbound_pending: int = 0,
    ) -> None:
        """
        Update connection counts from connection dictionary.

        Parameters
        ----------
        connections : dict
            Dictionary mapping peer IDs to lists of connections
        inbound_pending : int
            Number of pending inbound connections
        outbound_pending : int
            Number of pending outbound connections

        """
        self.inbound_connections = 0
        self.outbound_connections = 0
        self.inbound_pending = inbound_pending
        self.outbound_pending = outbound_pending

        total_connections = 0
        for conn_list in connections.values():
            for conn in conn_list:
                total_connections += 1
                # Determine direction - connections may track direction in future
                # For now, we can't distinguish, so we'll track total only
                # TODO: Add direction tracking to connections when implementing
                # connection state management
                if hasattr(conn, "direction"):
                    direction = getattr(conn, "direction")
                    if direction == "inbound":  # type: ignore
                        self.inbound_connections += 1
                    elif direction == "outbound":  # type: ignore
                        self.outbound_connections += 1

        # If direction is not tracked, we can't distinguish inbound/outbound
        # This will be addressed in Phase 6 when we add connection state tracking

    def update_stream_metrics(self, connections: dict[ID, list[INetConn]]) -> None:
        """
        Update protocol stream metrics from connections.

        Parameters
        ----------
        connections : dict
            Dictionary mapping peer IDs to lists of connections

        """
        # Reset metrics
        self.protocol_streams.clear()
        self._protocol_stream_counts.clear()

        for conn_list in connections.values():
            for conn in conn_list:
                # Get streams from connection
                streams: list[INetStream] = list(
                    getattr(conn, "get_streams", lambda: [])()
                )
                if not streams:
                    continue

                # Track streams per protocol
                protocol_counts: dict[str, int] = defaultdict(int)

                for stream in streams:
                    # Get protocol from stream
                    protocol = getattr(stream, "protocol_id", None)
                    if protocol is None:
                        protocol = "unnegotiated"
                    else:
                        # Convert TProtocol to string if needed
                        protocol = str(protocol)

                    # Direction tracking: Currently not available in Python libp2p
                    # We'll track as "unknown" for now
                    direction = "unknown"
                    # TODO: Add direction tracking when connection state
                    # management is implemented
                    # Note: JS libp2p uses "{direction} {protocol}" format
                    # We'll use "{protocol}" until direction tracking is added

                    # Create key: "{direction} {protocol}" (matching JS format)
                    # For now: "{protocol}" until direction is available
                    key = f"{direction} {protocol}"
                    protocol_counts[key] += 1
                    self.protocol_streams[key] += 1

                # Store stream counts per connection for percentile calculation
                for key, count in protocol_counts.items():
                    self._protocol_stream_counts[key].append(count)

    def get_protocol_streams_per_connection_90th_percentile(
        self,
    ) -> dict[str, float]:
        """
        Calculate 90th percentile of streams per connection per protocol.

        Returns
        -------
        dict[str, float]
            Dictionary mapping protocol keys to 90th percentile stream counts

        """
        result: dict[str, float] = {}

        for protocol, counts in self._protocol_stream_counts.items():
            if not counts:
                continue

            # Sort counts for percentile calculation
            sorted_counts = sorted(counts)
            index = int(len(sorted_counts) * 0.9)

            # Get 90th percentile value
            if index < len(sorted_counts):
                result[protocol] = float(sorted_counts[index])
            else:
                # If index is out of bounds, use max value
                result[protocol] = float(sorted_counts[-1]) if sorted_counts else 0.0

        return result

    def to_dict(self) -> dict[str, Any]:
        """
        Convert metrics to dictionary format.

        Returns
        -------
        dict
            Dictionary representation of all metrics

        """
        return {
            "connections": {
                "inbound": self.inbound_connections,
                "inbound_pending": self.inbound_pending,
                "outbound": self.outbound_connections,
                "outbound_pending": self.outbound_pending,
            },
            "protocol_streams_total": dict(self.protocol_streams),
            "protocol_streams_per_connection_90th_percentile": (
                self.get_protocol_streams_per_connection_90th_percentile()
            ),
        }

    def reset(self) -> None:
        """Reset all metrics to zero."""
        self.inbound_connections = 0
        self.outbound_connections = 0
        self.inbound_pending = 0
        self.outbound_pending = 0
        self.protocol_streams.clear()
        self._protocol_stream_counts.clear()


def calculate_connection_metrics(
    connections: dict[ID, list[INetConn]],
    inbound_pending: int = 0,
    outbound_pending: int = 0,
) -> ConnectionMetrics:
    """
    Calculate connection metrics from connection state.

    This function calculates metrics on-demand, matching JS libp2p behavior.

    Parameters
    ----------
    connections : dict
        Dictionary mapping peer IDs to lists of connections
    inbound_pending : int
        Number of pending inbound connections
    outbound_pending : int
        Number of pending outbound connections

    Returns
    -------
    ConnectionMetrics
        Calculated metrics object

    """
    metrics = ConnectionMetrics()
    metrics.update_connection_counts(connections, inbound_pending, outbound_pending)
    metrics.update_stream_metrics(connections)
    return metrics

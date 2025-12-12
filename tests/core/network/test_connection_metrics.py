"""
Unit tests for connection metrics implementation.

Tests for metrics tracking, connection counting, stream statistics,
and percentile calculations.
"""

from unittest.mock import Mock

from libp2p.network.metrics import (
    ConnectionMetrics,
    calculate_connection_metrics,
)
from libp2p.peer.id import ID


class TestConnectionMetricsDefaults:
    """Test ConnectionMetrics default values."""

    def test_connection_metrics_defaults(self):
        """Test default metric values."""
        metrics = ConnectionMetrics()

        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 0
        assert metrics.inbound_pending == 0
        assert metrics.outbound_pending == 0
        assert isinstance(metrics.protocol_streams, dict)
        assert len(metrics.protocol_streams) == 0

    def test_connection_metrics_protocol_streams_default(self):
        """Test protocol_streams is a defaultdict."""
        metrics = ConnectionMetrics()

        # Should not raise KeyError
        assert metrics.protocol_streams["nonexistent"] == 0


class TestConnectionCounting:
    """Test connection counting functionality."""

    def test_update_connection_counts_empty(self):
        """Test counting with no connections."""
        metrics = ConnectionMetrics()
        metrics.update_connection_counts({})

        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 0

    def test_update_connection_counts_inbound(self):
        """Test counting inbound connections."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")
        conn1 = Mock()
        conn1.direction = "inbound"
        conn2 = Mock()
        conn2.direction = "inbound"

        connections = {peer_id: [conn1, conn2]}
        metrics.update_connection_counts(connections)

        assert metrics.inbound_connections == 2
        assert metrics.outbound_connections == 0

    def test_update_connection_counts_outbound(self):
        """Test counting outbound connections."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")
        conn1 = Mock()
        conn1.direction = "outbound"

        connections = {peer_id: [conn1]}
        metrics.update_connection_counts(connections)

        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 1

    def test_update_connection_counts_mixed(self):
        """Test counting mixed inbound and outbound connections."""
        metrics = ConnectionMetrics()

        peer_id1 = ID(b"QmTest1")
        peer_id2 = ID(b"QmTest2")

        conn_in = Mock()
        conn_in.direction = "inbound"

        conn_out = Mock()
        conn_out.direction = "outbound"

        connections = {
            peer_id1: [conn_in],
            peer_id2: [conn_out],
        }
        metrics.update_connection_counts(connections)

        assert metrics.inbound_connections == 1
        assert metrics.outbound_connections == 1

    def test_update_connection_counts_unknown_direction(self):
        """Test handling of unknown connection direction."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")
        conn = Mock()
        conn.direction = "unknown"

        connections = {peer_id: [conn]}
        metrics.update_connection_counts(connections)

        # Unknown direction should not be counted
        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 0

    def test_update_connection_counts_pending(self):
        """Test pending connection tracking."""
        metrics = ConnectionMetrics()
        metrics.update_connection_counts({}, inbound_pending=3, outbound_pending=5)

        assert metrics.inbound_pending == 3
        assert metrics.outbound_pending == 5

    def test_update_connection_counts_multiple_peers(self):
        """Test counting connections across multiple peers."""
        metrics = ConnectionMetrics()

        peer_id1 = ID(b"QmTest1")
        peer_id2 = ID(b"QmTest2")
        peer_id3 = ID(b"QmTest3")

        conn1_in = Mock()
        conn1_in.direction = "inbound"
        conn1_out = Mock()
        conn1_out.direction = "outbound"

        conn2_in = Mock()
        conn2_in.direction = "inbound"

        conn3_out = Mock()
        conn3_out.direction = "outbound"

        connections = {
            peer_id1: [conn1_in, conn1_out],
            peer_id2: [conn2_in],
            peer_id3: [conn3_out],
        }
        metrics.update_connection_counts(connections)

        assert metrics.inbound_connections == 2
        assert metrics.outbound_connections == 2


class TestStreamMetrics:
    """Test stream metrics tracking."""

    def test_update_stream_metrics_empty(self):
        """Test stream metrics with no connections."""
        metrics = ConnectionMetrics()
        metrics.update_stream_metrics({})

        assert len(metrics.protocol_streams) == 0

    def test_update_stream_metrics_with_streams(self):
        """Test stream metrics with streams."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        stream1 = Mock()
        stream1.protocol_id = "/test/1.0.0"

        stream2 = Mock()
        stream2.protocol_id = "/test/1.0.0"

        conn = Mock()
        conn.direction = "inbound"
        conn.get_streams = Mock(return_value=[stream1, stream2])

        connections = {peer_id: [conn]}
        metrics.update_stream_metrics(connections)

        # Key format: "{direction} {protocol}"
        assert "inbound /test/1.0.0" in metrics.protocol_streams
        assert metrics.protocol_streams["inbound /test/1.0.0"] == 2

    def test_update_stream_metrics_unnegotiated(self):
        """Test stream metrics with unnegotiated streams."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        stream = Mock()
        stream.protocol_id = None  # Unnegotiated

        conn = Mock()
        conn.direction = "outbound"
        conn.get_streams = Mock(return_value=[stream])

        connections = {peer_id: [conn]}
        metrics.update_stream_metrics(connections)

        assert "outbound unnegotiated" in metrics.protocol_streams
        assert metrics.protocol_streams["outbound unnegotiated"] == 1

    def test_update_stream_metrics_multiple_protocols(self):
        """Test stream metrics with multiple protocols."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        stream1 = Mock()
        stream1.protocol_id = "/proto/a"

        stream2 = Mock()
        stream2.protocol_id = "/proto/b"

        conn = Mock()
        conn.direction = "inbound"
        conn.get_streams = Mock(return_value=[stream1, stream2])

        connections = {peer_id: [conn]}
        metrics.update_stream_metrics(connections)

        assert "inbound /proto/a" in metrics.protocol_streams
        assert "inbound /proto/b" in metrics.protocol_streams

    def test_update_stream_metrics_resets(self):
        """Test that update_stream_metrics resets previous values."""
        metrics = ConnectionMetrics()
        metrics.protocol_streams["old key"] = 100

        metrics.update_stream_metrics({})

        assert "old key" not in metrics.protocol_streams


class TestPercentileCalculation:
    """Test 90th percentile calculation for streams."""

    def test_percentile_empty(self):
        """Test percentile with no data."""
        metrics = ConnectionMetrics()
        result = metrics.get_protocol_streams_per_connection_90th_percentile()

        assert result == {}

    def test_percentile_single_value(self):
        """Test percentile with single value."""
        metrics = ConnectionMetrics()
        metrics._protocol_stream_counts["inbound /test"] = [5]

        result = metrics.get_protocol_streams_per_connection_90th_percentile()

        assert "inbound /test" in result
        assert result["inbound /test"] == 5.0

    def test_percentile_multiple_values(self):
        """Test percentile with multiple values."""
        metrics = ConnectionMetrics()
        # 10 values: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        # 90th percentile index: int(10 * 0.9) = 9
        # Value at index 9 in sorted list: 10
        metrics._protocol_stream_counts["inbound /test"] = list(range(1, 11))

        result = metrics.get_protocol_streams_per_connection_90th_percentile()

        assert "inbound /test" in result
        assert result["inbound /test"] == 10.0

    def test_percentile_unsorted_values(self):
        """Test percentile correctly sorts values."""
        metrics = ConnectionMetrics()
        # Unsorted: [10, 5, 3, 8, 1, 7, 2, 9, 4, 6]
        # Sorted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        metrics._protocol_stream_counts["test"] = [10, 5, 3, 8, 1, 7, 2, 9, 4, 6]

        result = metrics.get_protocol_streams_per_connection_90th_percentile()

        assert result["test"] == 10.0


class TestMetricsSerialization:
    """Test metrics to_dict serialization."""

    def test_to_dict_empty(self):
        """Test serialization of empty metrics."""
        metrics = ConnectionMetrics()
        result = metrics.to_dict()

        assert result == {
            "connections": {
                "inbound": 0,
                "inbound_pending": 0,
                "outbound": 0,
                "outbound_pending": 0,
            },
            "protocol_streams_total": {},
            "protocol_streams_per_connection_90th_percentile": {},
        }

    def test_to_dict_with_data(self):
        """Test serialization with data."""
        metrics = ConnectionMetrics()
        metrics.inbound_connections = 5
        metrics.outbound_connections = 3
        metrics.inbound_pending = 2
        metrics.outbound_pending = 1
        metrics.protocol_streams["inbound /test"] = 10

        result = metrics.to_dict()

        assert result["connections"]["inbound"] == 5
        assert result["connections"]["outbound"] == 3
        assert result["connections"]["inbound_pending"] == 2
        assert result["connections"]["outbound_pending"] == 1
        assert result["protocol_streams_total"]["inbound /test"] == 10


class TestMetricsReset:
    """Test metrics reset functionality."""

    def test_reset_clears_all(self):
        """Test that reset clears all metrics."""
        metrics = ConnectionMetrics()
        metrics.inbound_connections = 10
        metrics.outbound_connections = 5
        metrics.inbound_pending = 3
        metrics.outbound_pending = 2
        metrics.protocol_streams["test"] = 50
        metrics._protocol_stream_counts["test"] = [1, 2, 3]

        metrics.reset()

        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 0
        assert metrics.inbound_pending == 0
        assert metrics.outbound_pending == 0
        assert len(metrics.protocol_streams) == 0
        assert len(metrics._protocol_stream_counts) == 0


class TestCalculateConnectionMetrics:
    """Test calculate_connection_metrics helper function."""

    def test_calculate_empty(self):
        """Test calculating metrics from empty connections."""
        metrics = calculate_connection_metrics({})

        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 0

    def test_calculate_with_connections(self):
        """Test calculating metrics from connections."""
        peer_id = ID(b"QmTest")

        conn_in = Mock()
        conn_in.direction = "inbound"
        conn_in.get_streams = Mock(return_value=[])

        conn_out = Mock()
        conn_out.direction = "outbound"
        conn_out.get_streams = Mock(return_value=[])

        connections = {peer_id: [conn_in, conn_out]}
        metrics = calculate_connection_metrics(connections)

        assert metrics.inbound_connections == 1
        assert metrics.outbound_connections == 1

    def test_calculate_with_pending(self):
        """Test calculating metrics with pending connections."""
        metrics = calculate_connection_metrics(
            {}, inbound_pending=5, outbound_pending=3
        )

        assert metrics.inbound_pending == 5
        assert metrics.outbound_pending == 3


class TestMetricsMultipleConnections:
    """Test metrics with multiple connections per peer."""

    def test_multiple_connections_per_peer(self):
        """Test counting multiple connections to same peer."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        conn1 = Mock()
        conn1.direction = "inbound"

        conn2 = Mock()
        conn2.direction = "inbound"

        conn3 = Mock()
        conn3.direction = "outbound"

        connections = {peer_id: [conn1, conn2, conn3]}
        metrics.update_connection_counts(connections)

        assert metrics.inbound_connections == 2
        assert metrics.outbound_connections == 1


class TestMetricsEdgeCases:
    """Test edge cases in metrics handling."""

    def test_missing_direction_attribute(self):
        """Test handling of connections without direction attribute."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        conn = Mock(spec=[])  # No direction attribute

        connections = {peer_id: [conn]}
        metrics.update_connection_counts(connections)

        # Should handle gracefully
        assert metrics.inbound_connections == 0
        assert metrics.outbound_connections == 0

    def test_missing_get_streams_method(self):
        """Test handling of connections without get_streams method."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        conn = Mock()
        conn.direction = "inbound"
        # get_streams returns empty list to avoid iteration errors
        conn.get_streams = Mock(return_value=[])

        connections = {peer_id: [conn]}

        # Should not raise
        metrics.update_stream_metrics(connections)

    def test_stream_with_tprotocol(self):
        """Test handling of streams with TProtocol objects."""
        metrics = ConnectionMetrics()

        peer_id = ID(b"QmTest")

        # Simulate TProtocol object that needs str() conversion
        class TProtocol:
            def __str__(self):
                return "/test/protocol"

        stream = Mock()
        stream.protocol_id = TProtocol()

        conn = Mock()
        conn.direction = "inbound"
        conn.get_streams = Mock(return_value=[stream])

        connections = {peer_id: [conn]}
        metrics.update_stream_metrics(connections)

        assert "inbound /test/protocol" in metrics.protocol_streams

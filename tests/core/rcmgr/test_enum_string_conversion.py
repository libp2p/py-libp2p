"""
Test cases for enum string conversion fixes.

This module tests the Direction and MetricType enum string conversion
that was fixed to resolve AssertionError failures in CI.
"""

from libp2p.rcmgr import Direction
from libp2p.rcmgr.metrics import MetricType


class TestEnumStringConversion:
    """Test enum string conversion functionality."""

    def test_direction_enum_string_conversion(self):
        """Test that Direction enum returns numeric string values."""
        # Test INBOUND direction
        assert str(Direction.INBOUND) == "0"
        assert Direction.INBOUND.value == 0

        # Test OUTBOUND direction
        assert str(Direction.OUTBOUND) == "1"
        assert Direction.OUTBOUND.value == 1

    def test_metric_type_enum_string_conversion(self):
        """Test that MetricType enum returns numeric string values."""
        # Test various metric types
        assert str(MetricType.CONNECTIONS_INBOUND) == "0"
        assert str(MetricType.CONNECTIONS_OUTBOUND) == "1"
        assert str(MetricType.MEMORY_USAGE) == "2"
        assert str(MetricType.STREAMS_INBOUND) == "3"
        assert str(MetricType.STREAMS_OUTBOUND) == "4"
        assert str(MetricType.CONNECTION_BLOCKS) == "5"
        assert str(MetricType.MEMORY_BLOCKS) == "6"
        assert str(MetricType.STREAM_BLOCKS) == "7"
        assert str(MetricType.PEAK_CONNECTIONS) == "8"
        assert str(MetricType.PEAK_MEMORY) == "9"
        assert str(MetricType.PEAK_STREAMS) == "10"

    def test_enum_values_unchanged(self):
        """Test that enum values remain unchanged after string conversion fix."""
        # Verify Direction enum values
        assert Direction.INBOUND == 0
        assert Direction.OUTBOUND == 1

        # Verify MetricType enum values
        assert MetricType.CONNECTIONS_INBOUND == 0
        assert MetricType.CONNECTIONS_OUTBOUND == 1
        assert MetricType.MEMORY_USAGE == 2
        assert MetricType.STREAMS_INBOUND == 3
        assert MetricType.STREAMS_OUTBOUND == 4
        assert MetricType.CONNECTION_BLOCKS == 5
        assert MetricType.MEMORY_BLOCKS == 6
        assert MetricType.STREAM_BLOCKS == 7
        assert MetricType.PEAK_CONNECTIONS == 8
        assert MetricType.PEAK_MEMORY == 9
        assert MetricType.PEAK_STREAMS == 10

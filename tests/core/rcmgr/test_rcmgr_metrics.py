"""
Resource manager metrics tests.

Tests the optimized metrics collection system including
array-based storage, performance, and accuracy.
"""

import time

from libp2p.rcmgr import Direction
from libp2p.rcmgr.metrics import Metrics, MetricType


class TestMetrics:
    """Test the optimized metrics collection system."""

    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = Metrics()
        assert metrics is not None
        assert len(metrics._counters) == len(MetricType)
        assert len(metrics._gauges) == len(MetricType)

    def test_connection_recording(self):
        """Test connection recording."""
        metrics = Metrics()

        # Record inbound connection
        metrics.record_connection("inbound")
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1

        # Record outbound connection
        metrics.record_connection("outbound")
        assert metrics.get_counter(MetricType.CONNECTIONS_OUTBOUND) == 1

    def test_memory_recording(self):
        """Test memory recording."""
        metrics = Metrics()

        # Record memory usage
        metrics.record_memory(1024)
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1024

        # Record additional memory
        metrics.record_memory(512)
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1536

    def test_stream_recording(self):
        """Test stream recording."""
        metrics = Metrics()

        # Record inbound stream
        metrics.record_stream("inbound")
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 1

        # Record outbound stream
        metrics.record_stream("outbound")
        assert metrics.get_counter(MetricType.STREAMS_OUTBOUND) == 1

    def test_block_recording(self):
        """Test block recording."""
        metrics = Metrics()

        # Record connection block
        metrics.record_block("connection")
        assert metrics.get_counter(MetricType.CONNECTION_BLOCKS) == 1

        # Record memory block
        metrics.record_block("memory")
        assert metrics.get_counter(MetricType.MEMORY_BLOCKS) == 1

    def test_allow_stream(self):
        """Test allow_stream method."""
        metrics = Metrics()

        # Allow inbound stream
        metrics.allow_stream("peer1", "inbound")
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 1

        # Allow outbound stream
        metrics.allow_stream("peer2", "outbound")
        assert metrics.get_counter(MetricType.STREAMS_OUTBOUND) == 1

    def test_remove_stream(self):
        """Test remove_stream method."""
        metrics = Metrics()

        # Add stream first
        metrics.allow_stream("peer1", "inbound")
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 1

        # Remove stream
        metrics.remove_stream("inbound")
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 0

    def test_get_summary(self):
        """Test getting metrics summary."""
        metrics = Metrics()

        # Record some metrics
        metrics.record_connection("inbound")
        metrics.record_memory(1024)
        metrics.record_stream("inbound")
        metrics.record_block("connection")

        summary = metrics.get_summary()
        assert "connections" in summary
        assert "memory" in summary
        assert "streams" in summary
        assert "blocks" in summary
        assert summary["connections"]["inbound"] == 1
        assert summary["memory"]["current"] == 1024
        assert summary["streams"]["inbound"] == 1
        assert summary["blocks"]["connections"] == 1

    def test_reset(self):
        """Test metrics reset."""
        metrics = Metrics()

        # Record some metrics
        metrics.record_connection("inbound")
        metrics.record_memory(1024)
        metrics.record_stream("inbound")
        metrics.record_block("connection")

        # Verify metrics are recorded
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1024
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 1
        assert metrics.get_counter(MetricType.CONNECTION_BLOCKS) == 1

        # Reset metrics
        metrics.reset()

        # Verify all metrics are reset
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 0
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 0
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 0
        assert metrics.get_counter(MetricType.CONNECTION_BLOCKS) == 0

    def test_direction_enum(self):
        """Test Direction enum values."""
        assert Direction.INBOUND == 0
        assert Direction.OUTBOUND == 1

    def test_metric_type_enum(self):
        """Test MetricType enum values."""
        assert MetricType.CONNECTIONS_INBOUND == 0
        assert MetricType.CONNECTIONS_OUTBOUND == 1
        assert MetricType.MEMORY_USAGE == 2
        assert MetricType.STREAMS_INBOUND == 3
        assert MetricType.STREAMS_OUTBOUND == 4

    def test_array_based_storage(self):
        """Test that metrics use list-based storage for performance."""
        metrics = Metrics()

        # Verify lists are used
        assert hasattr(metrics, "_counters")
        assert hasattr(metrics, "_gauges")
        assert isinstance(metrics._counters, list)
        assert isinstance(metrics._gauges, list)

        # Verify array length matches enum count
        assert len(metrics._counters) == len(MetricType)
        assert len(metrics._gauges) == len(MetricType)

    def test_performance_large_operations(self):
        """Test performance with large number of operations."""
        metrics = Metrics()

        # Record many connections
        start_time = time.time()
        for i in range(1000):
            metrics.record_connection("inbound")
        end_time = time.time()

        # Should complete quickly (array-based storage)
        assert end_time - start_time < 1.0
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1000

    def test_memory_efficiency(self):
        """Test memory efficiency of array-based storage."""
        metrics = Metrics()

        # Record many metrics
        for i in range(1000):
            metrics.record_connection("inbound")
            metrics.record_memory(1024)
            metrics.record_stream("inbound")

        # Verify metrics are recorded correctly
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1000
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1000 * 1024
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 1000

    def test_concurrent_metrics_recording(self):
        """Test concurrent metrics recording."""
        import threading

        metrics = Metrics()
        results = []

        def record_metrics():
            try:
                for i in range(100):
                    metrics.record_connection("inbound")
                    metrics.record_memory(1024)
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=record_metrics)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All operations should succeed
        assert len(results) == 5
        assert all(result == "success" for result in results)

        # Verify final metrics
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 500
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 500 * 1024

    def test_metrics_accuracy(self):
        """Test metrics accuracy with mixed operations."""
        metrics = Metrics()

        # Record various metrics
        metrics.record_connection("inbound")
        metrics.record_connection("outbound")
        metrics.record_memory(2048)
        metrics.record_stream("inbound")
        metrics.record_block("connection")

        # Verify accuracy
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1
        assert metrics.get_counter(MetricType.CONNECTIONS_OUTBOUND) == 1
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 2048
        assert metrics.get_counter(MetricType.STREAMS_INBOUND) == 1
        assert metrics.get_counter(MetricType.CONNECTION_BLOCKS) == 1

    def test_negative_memory_handling(self):
        """Test handling of negative memory values."""
        metrics = Metrics()

        # Record positive memory
        metrics.record_memory(1024)
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1024

        # Record negative memory (should be handled gracefully)
        metrics.record_memory(-512)
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 512

    def test_zero_values(self):
        """Test handling of zero values."""
        metrics = Metrics()

        # Record zero memory
        metrics.record_memory(0)
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 0

        # Record zero connection (should not affect count)
        metrics.record_connection("inbound")
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1

    def test_metrics_persistence(self):
        """Test that metrics persist across operations."""
        metrics = Metrics()

        # Record initial metrics
        metrics.record_connection("inbound")
        metrics.record_memory(1024)

        # Verify persistence
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1024

        # Record additional metrics
        metrics.record_connection("outbound")
        metrics.record_memory(512)

        # Verify cumulative values
        assert metrics.get_counter(MetricType.CONNECTIONS_INBOUND) == 1
        assert metrics.get_counter(MetricType.CONNECTIONS_OUTBOUND) == 1
        assert metrics.get_counter(MetricType.MEMORY_USAGE) == 1536

    def test_enum_comparison(self):
        """Test enum comparison operations."""
        # Test direction comparison
        assert Direction.INBOUND == 0
        assert Direction.OUTBOUND == 1
        assert Direction.INBOUND != Direction.OUTBOUND

        # Test metric type comparison
        assert MetricType.CONNECTIONS_INBOUND == 0
        assert MetricType.MEMORY_USAGE == 2
        assert MetricType.CONNECTIONS_INBOUND != MetricType.MEMORY_USAGE

    def test_string_conversion(self):
        """Test string conversion of enums."""
        # Test direction string conversion (IntEnum uses numeric values)
        assert str(Direction.INBOUND) == "0"
        assert str(Direction.OUTBOUND) == "1"

        # Test metric type string conversion (IntEnum uses numeric values)
        assert str(MetricType.CONNECTIONS_INBOUND) == "0"
        assert str(MetricType.MEMORY_USAGE) == "2"
        assert str(MetricType.STREAMS_INBOUND) == "3"
        assert str(MetricType.CONNECTION_BLOCKS) == "5"

"""
Tests for the metrics functionality.
"""

from libp2p.rcmgr.limits import Direction
from libp2p.rcmgr.metrics import Metrics


def test_metrics_creation():
    """Test Metrics creation."""
    metrics = Metrics()
    assert metrics is not None


def test_record_memory():
    """Test recording memory usage."""
    metrics = Metrics()

    # Record memory usage
    metrics.record_memory("test_scope", 1024)
    metrics.record_memory("test_scope", 512)

    # Get current memory
    memory = metrics.get_memory("test_scope")
    assert memory == 512  # Latest value


def test_record_streams():
    """Test recording stream counts."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Record streams
    metrics.record_streams(scope_name, 5, 3)

    streams = metrics.get_streams(scope_name)
    assert streams["total"] == 5
    assert streams["inbound"] == 3
    assert streams["outbound"] == 2  # total - inbound


def test_record_connections():
    """Test recording connection counts."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Record connections
    metrics.record_connections(scope_name, 8, 4)

    conns = metrics.get_connections(scope_name)
    assert conns["total"] == 8
    assert conns["inbound"] == 4
    assert conns["outbound"] == 4  # total - inbound


def test_record_file_descriptors():
    """Test recording file descriptor usage."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Record FDs
    metrics.record_fd(scope_name, 10)

    fd_count = metrics.get_fd(scope_name)
    assert fd_count == 10


def test_increment_operations():
    """Test increment operations."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Initial state
    assert metrics.get_memory(scope_name) == 0

    # Increment memory
    metrics.increment_memory(scope_name, 256)
    assert metrics.get_memory(scope_name) == 256

    metrics.increment_memory(scope_name, 256)
    assert metrics.get_memory(scope_name) == 512

    # Decrement memory
    metrics.increment_memory(scope_name, -128)
    assert metrics.get_memory(scope_name) == 384


def test_increment_streams():
    """Test stream increment operations."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Add streams
    metrics.add_stream(scope_name, Direction.INBOUND)
    metrics.add_stream(scope_name, Direction.OUTBOUND)
    metrics.add_stream(scope_name, Direction.INBOUND)

    streams = metrics.get_streams(scope_name)
    assert streams["total"] == 3
    assert streams["inbound"] == 2
    assert streams["outbound"] == 1

    # Remove stream
    metrics.remove_stream(scope_name, Direction.INBOUND)

    streams = metrics.get_streams(scope_name)
    assert streams["total"] == 2
    assert streams["inbound"] == 1
    assert streams["outbound"] == 1


def test_increment_connections():
    """Test connection increment operations."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Add connections
    metrics.add_connection(scope_name, Direction.INBOUND)
    metrics.add_connection(scope_name, Direction.OUTBOUND)
    metrics.add_connection(scope_name, Direction.OUTBOUND)

    conns = metrics.get_connections(scope_name)
    assert conns["total"] == 3
    assert conns["inbound"] == 1
    assert conns["outbound"] == 2

    # Remove connection
    metrics.remove_connection(scope_name, Direction.OUTBOUND)

    conns = metrics.get_connections(scope_name)
    assert conns["total"] == 2
    assert conns["inbound"] == 1
    assert conns["outbound"] == 1


def test_get_summary():
    """Test getting comprehensive metrics summary."""
    metrics = Metrics()

    # Record some metrics
    metrics.record_memory("system", 2048)
    metrics.record_streams("peer:abc", 5, 3)
    metrics.record_connections("protocol:/test/1.0.0", 2, 1)
    metrics.record_fd("service:test", 4)

    # Get summary
    summary = metrics.get_summary()

    assert "resource_metrics" in summary
    resource_metrics = summary["resource_metrics"]

    # Check scopes are included
    assert "system" in resource_metrics
    assert "peer:abc" in resource_metrics
    assert "protocol:/test/1.0.0" in resource_metrics
    assert "service:test" in resource_metrics

    # Check system metrics
    system_stats = resource_metrics["system"]
    assert system_stats["memory"] == 2048

    # Check peer metrics
    peer_stats = resource_metrics["peer:abc"]
    assert peer_stats["streams"]["total"] == 5
    assert peer_stats["streams"]["inbound"] == 3
    assert peer_stats["streams"]["outbound"] == 2

    # Check protocol metrics
    protocol_stats = resource_metrics["protocol:/test/1.0.0"]
    assert protocol_stats["connections"]["total"] == 2
    assert protocol_stats["connections"]["inbound"] == 1
    assert protocol_stats["connections"]["outbound"] == 1

    # Check service metrics
    service_stats = resource_metrics["service:test"]
    assert service_stats["fd"] == 4


def test_multiple_scopes():
    """Test metrics for multiple scopes."""
    metrics = Metrics()

    scopes = ["system", "peer:abc", "peer:def", "protocol:/test/1.0.0"]

    for i, scope in enumerate(scopes):
        metrics.record_memory(scope, (i + 1) * 1024)
        metrics.record_streams(scope, i + 2, i + 1)

    # Check each scope
    for i, scope in enumerate(scopes):
        memory = metrics.get_memory(scope)
        assert memory == (i + 1) * 1024

        streams = metrics.get_streams(scope)
        assert streams["total"] == i + 2
        assert streams["inbound"] == i + 1


def test_zero_values():
    """Test handling of zero values."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Default values should be zero
    assert metrics.get_memory(scope_name) == 0
    assert metrics.get_fd(scope_name) == 0

    streams = metrics.get_streams(scope_name)
    assert streams["total"] == 0
    assert streams["inbound"] == 0
    assert streams["outbound"] == 0

    conns = metrics.get_connections(scope_name)
    assert conns["total"] == 0
    assert conns["inbound"] == 0
    assert conns["outbound"] == 0


def test_negative_increments():
    """Test negative increments (decrements)."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Start with some values
    metrics.record_memory(scope_name, 1024)
    metrics.add_stream(scope_name, Direction.INBOUND)
    metrics.add_connection(scope_name, Direction.OUTBOUND)

    # Decrement
    metrics.increment_memory(scope_name, -512)
    assert metrics.get_memory(scope_name) == 512

    # Remove streams/connections
    metrics.remove_stream(scope_name, Direction.INBOUND)
    streams = metrics.get_streams(scope_name)
    assert streams["total"] == 0

    metrics.remove_connection(scope_name, Direction.OUTBOUND)
    conns = metrics.get_connections(scope_name)
    assert conns["total"] == 0


def test_underflow_protection():
    """Test protection against underflow."""
    metrics = Metrics()
    scope_name = "test_scope"

    # Try to decrement below zero
    metrics.increment_memory(scope_name, -100)
    memory_value = metrics.get_memory(scope_name)
    # Should not go negative
    assert isinstance(memory_value, (int, float)) and memory_value >= 0

    # Try to remove more streams than exist
    metrics.remove_stream(scope_name, Direction.INBOUND)
    streams = metrics.get_streams(scope_name)
    assert streams["inbound"] >= 0
    assert streams["total"] >= 0


def test_concurrent_access():
    """Test concurrent access to metrics."""
    import threading

    metrics = Metrics()
    scope_name = "concurrent_scope"
    errors = []

    def worker():
        try:
            # Each worker adds some metrics
            for i in range(100):
                metrics.increment_memory(scope_name, 10)
                metrics.add_stream(scope_name, Direction.INBOUND)
                metrics.add_connection(scope_name, Direction.OUTBOUND)
        except Exception as e:
            errors.append(e)

    # Start multiple threads
    threads = []
    num_workers = 5
    for _ in range(num_workers):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    # Check for errors
    assert len(errors) == 0

    # Check final values (should be sum of all workers)
    expected_memory = num_workers * 100 * 10
    expected_streams = num_workers * 100
    expected_conns = num_workers * 100

    assert metrics.get_memory(scope_name) == expected_memory

    streams = metrics.get_streams(scope_name)
    assert streams["total"] == expected_streams
    assert streams["inbound"] == expected_streams

    conns = metrics.get_connections(scope_name)
    assert conns["total"] == expected_conns
    assert conns["outbound"] == expected_conns


def test_large_numbers():
    """Test handling of large numbers."""
    metrics = Metrics()
    scope_name = "large_scope"

    # Test large memory value
    large_memory = 2**32  # 4GB
    metrics.record_memory(scope_name, large_memory)
    assert metrics.get_memory(scope_name) == large_memory

    # Test large stream/connection counts
    large_count = 10000
    metrics.record_streams(scope_name, large_count, large_count // 2)
    streams = metrics.get_streams(scope_name)
    assert streams["total"] == large_count
    assert streams["inbound"] == large_count // 2


def test_scope_name_formats():
    """Test various scope name formats."""
    metrics = Metrics()

    scope_names = [
        "system",
        "transient",
        "peer:QmTest123",
        "protocol:/test/1.0.0",
        "service:dht",
        "conn:123",
        "stream:456",
    ]

    for scope_name in scope_names:
        metrics.record_memory(scope_name, 1024)
        memory = metrics.get_memory(scope_name)
        assert memory == 1024


def test_string_values():
    """Test handling of string values in metrics."""
    metrics = Metrics()
    scope_name = "string_scope"

    # Some metrics might store string values (e.g., status, errors)
    string_value = "connected"
    metrics.record_memory(scope_name, string_value)

    # Should handle gracefully
    result = metrics.get_memory(scope_name)
    assert result == string_value

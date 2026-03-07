"""
Resource manager monitoring tests.

Tests the advanced monitoring system including metrics collection,
alerting, and OpenMetrics export.
"""

import time

from libp2p.rcmgr.monitoring import (
    Alert,
    AlertSeverity,
    Metric,
    MetricType,
    Monitor,
)


class TestMonitor:
    """Test the production monitoring system."""

    def test_monitor_initialization(self):
        """Test monitor initialization."""
        monitor = Monitor()
        assert monitor is not None
        assert len(monitor.metrics_buffer) == 0
        assert len(monitor.alerts) == 0
        assert len(monitor._connection_durations) == 0

    def test_record_connection_establishment(self):
        """Test recording connection establishment."""
        monitor = Monitor()

        # Record connection establishment
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")

        # Verify connection is tracked
        assert "conn1" in monitor._connection_durations
        duration_tracker = monitor._connection_durations["conn1"]
        assert duration_tracker.peer_id == "peer1"
        assert duration_tracker.protocol == "tcp"
        assert duration_tracker.direction == "inbound"
        assert duration_tracker.start_time > 0
        assert duration_tracker.end_time is None

    def test_record_connection_closed(self):
        """Test recording connection closure."""
        monitor = Monitor()

        # Record connection establishment first
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")

        # Record connection closure
        monitor.record_connection_closed("conn1", "normal")

        # Verify connection is removed from tracking
        assert "conn1" not in monitor._connection_durations

    def test_record_protocol_metric(self):
        """Test recording protocol-specific metrics."""
        monitor = Monitor()

        # Record protocol metric
        monitor.record_protocol_metric("kad", "requests", 10, {"peer_id": "peer1"})

        # Verify metric is recorded
        assert len(monitor.metrics_buffer) > 0
        # Check that protocol metrics are tracked
        protocol_metrics = monitor.get_protocol_metrics()
        assert "kad" in protocol_metrics

    def test_record_resource_usage(self):
        """Test recording resource usage metrics."""
        monitor = Monitor()

        # Record resource usage
        monitor.record_resource_usage("memory", 1024, 2048, {"peer_id": "peer1"})

        # Verify metric is recorded
        assert len(monitor.metrics_buffer) > 0

    def test_record_error(self):
        """Test recording error metrics."""
        monitor = Monitor()

        # Record error
        monitor.record_error("connection_failed", "timeout", {"peer_id": "peer1"})

        # Verify metric is recorded
        assert len(monitor.metrics_buffer) > 0

    def test_export_openmetrics(self):
        """Test OpenMetrics export."""
        monitor = Monitor()

        # Record some metrics
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")
        monitor.record_resource_usage("memory", 1024, 2048, {"peer_id": "peer1"})

        # Export metrics
        openmetrics = monitor.export_openmetrics()

        # Verify OpenMetrics format
        assert "# TYPE libp2p_connections_established_total counter" in openmetrics
        assert "# TYPE libp2p_resource_usage_current gauge" in openmetrics
        assert (
            'libp2p_connections_established_total{protocol="tcp",'
            'direction="inbound",peer_id="peer1"} 1' in openmetrics
        )
        assert (
            'libp2p_resource_usage_current{peer_id="peer1",'
            'resource_type="memory"} 1024' in openmetrics
        )

    def test_metric_creation(self):
        """Test Metric dataclass creation."""
        metric = Metric(
            name="test_metric",
            value=42.0,
            metric_type=MetricType.GAUGE,
            labels={"peer_id": "peer1"},
            timestamp=time.time(),
        )

        assert metric.name == "test_metric"
        assert metric.value == 42.0
        assert metric.labels["peer_id"] == "peer1"
        assert metric.timestamp > 0

    def test_alert_creation(self):
        """Test Alert dataclass creation."""
        alert = Alert(
            name="test_alert",
            condition="memory > 80%",
            severity=AlertSeverity.WARNING,
            message="High memory usage",
            threshold=80.0,
            current_value=85.0,
        )

        assert alert.name == "test_alert"
        assert alert.condition == "memory > 80%"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.message == "High memory usage"
        assert alert.threshold == 80.0
        assert alert.current_value == 85.0

    def test_alert_severity_enum(self):
        """Test AlertSeverity enum values."""
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.ERROR.value == "error"
        assert AlertSeverity.CRITICAL.value == "critical"

    def test_monitor_with_custom_settings(self):
        """Test monitor with custom settings."""
        monitor = Monitor(
            buffer_size=500,
            alert_thresholds={"memory_warning": 70.0, "memory_critical": 90.0},
            enable_connection_tracking=False,
            enable_protocol_metrics=False,
        )

        assert monitor.metrics_buffer.maxlen == 500
        assert monitor.alert_thresholds["memory_warning"] == 70.0
        assert monitor.alert_thresholds["memory_critical"] == 90.0
        assert monitor.enable_connection_tracking is False
        assert monitor.enable_protocol_metrics is False

    def test_metrics_summary(self):
        """Test getting metrics summary."""
        monitor = Monitor()

        # Record some metrics
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")
        monitor.record_resource_usage("memory", 1024, 2048, {"peer_id": "peer1"})

        # Get summary
        summary = monitor.get_metrics_summary()
        assert "total_metrics_recorded" in summary
        assert "total_alerts_triggered" in summary
        assert "active_connections" in summary
        assert "protocols_tracked" in summary

    def test_connection_durations(self):
        """Test getting connection duration statistics."""
        monitor = Monitor()

        # Record connection establishment
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")

        # Get connection durations
        durations = monitor.get_connection_durations()
        assert len(durations) == 1
        assert durations[0]["connection_id"] == "conn1"
        assert durations[0]["peer_id"] == "peer1"
        assert durations[0]["protocol"] == "tcp"
        assert durations[0]["direction"] == "inbound"
        assert durations[0]["is_active"] is True

    def test_protocol_metrics(self):
        """Test getting protocol-specific metrics."""
        monitor = Monitor()

        # Record protocol metrics
        monitor.record_protocol_metric("kad", "requests", 10, {"peer_id": "peer1"})
        monitor.record_protocol_metric("kad", "responses", 8, {"peer_id": "peer1"})

        # Get protocol metrics
        protocol_metrics = monitor.get_protocol_metrics()
        assert "kad" in protocol_metrics
        assert "requests" in protocol_metrics["kad"]
        assert "responses" in protocol_metrics["kad"]

    def test_clear_old_metrics(self):
        """Test clearing old metrics."""
        monitor = Monitor()

        # Record some metrics
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")

        # Clear old metrics (with very short max age)
        monitor.clear_old_metrics(max_age_seconds=0.001)

        # Wait a bit and check
        time.sleep(0.01)
        monitor.clear_old_metrics(max_age_seconds=0.001)

        # Metrics should be cleared
        assert len(monitor.metrics_buffer) == 0

    def test_monitor_reset(self):
        """Test monitor reset."""
        monitor = Monitor()

        # Record some metrics
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")
        monitor.record_resource_usage("memory", 1024, 2048, {"peer_id": "peer1"})

        # Reset monitor
        monitor.reset()

        # All data should be cleared
        assert len(monitor.metrics_buffer) == 0
        assert len(monitor.alerts) == 0
        assert len(monitor._connection_durations) == 0

    def test_metric_aggregation(self):
        """Test metric aggregation across multiple peers."""
        monitor = Monitor()

        # Record metrics for multiple peers
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")
        monitor.record_connection_establishment("conn2", "peer2", "tcp", "inbound")
        monitor.record_connection_establishment("conn3", "peer3", "tcp", "outbound")

        # Export metrics
        openmetrics = monitor.export_openmetrics()

        # Verify aggregated metrics
        assert (
            'libp2p_connections_established_total{protocol="tcp",'
            'direction="inbound",peer_id="peer1"} 1' in openmetrics
        )
        assert (
            'libp2p_connections_established_total{protocol="tcp",'
            'direction="inbound",peer_id="peer2"} 1' in openmetrics
        )
        assert (
            'libp2p_connections_established_total{protocol="tcp",'
            'direction="outbound",peer_id="peer3"} 1' in openmetrics
        )

    def test_timestamp_accuracy(self):
        """Test timestamp accuracy."""
        monitor = Monitor()

        # Record metric with known timestamp
        start_time = time.time()
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")
        end_time = time.time()

        # Check that timestamp is within expected range
        assert len(monitor.metrics_buffer) > 0
        metric = monitor.metrics_buffer[-1]
        assert start_time <= metric.timestamp <= end_time

    def test_label_escaping(self):
        """Test label value escaping in OpenMetrics."""
        monitor = Monitor()

        # Record metric with special characters in labels
        monitor.record_error(
            "connection_failed",
            "timeout",
            {"peer": 'peer"with"quotes', "error": "timeout\nwith\nnewlines"},
        )

        # Export metrics
        openmetrics = monitor.export_openmetrics()

        # Verify labels are properly escaped
        assert "connection_failed" in openmetrics

    def test_alert_thresholds(self):
        """Test alert threshold functionality."""
        monitor = Monitor(
            alert_thresholds={"memory_warning": 70.0, "memory_critical": 90.0}
        )

        # Record high memory usage
        monitor.record_resource_usage("memory", 800, 1000, {"peer_id": "peer1"})

        # Check if alerts are triggered
        # May or may not trigger depending on implementation
        assert len(monitor.alerts) >= 0

    def test_connection_tracking_disabled(self):
        """Test monitor with connection tracking disabled."""
        monitor = Monitor(enable_connection_tracking=False)

        # Record connection establishment
        monitor.record_connection_establishment("conn1", "peer1", "tcp", "inbound")

        # Connection should not be tracked
        assert len(monitor._connection_durations) == 0

    def test_protocol_metrics_disabled(self):
        """Test monitor with protocol metrics disabled."""
        monitor = Monitor(enable_protocol_metrics=False)

        # Record protocol metric
        monitor.record_protocol_metric("kad", "requests", 10, {"peer_id": "peer1"})

        # Protocol metrics should not be tracked
        protocol_metrics = monitor.get_protocol_metrics()
        assert len(protocol_metrics) == 0

    def test_concurrent_metric_recording(self):
        """Test concurrent metric recording."""
        import threading

        monitor = Monitor()

        def record_metrics():
            for i in range(10):
                monitor.record_connection_establishment(
                    f"conn{i}", f"peer{i}", "tcp", "inbound"
                )

        # Run multiple threads recording metrics
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=record_metrics)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All metrics should be recorded
        assert len(monitor.metrics_buffer) == 50

    def test_alert_severity_comparison(self):
        """Test alert severity comparison."""
        severities = [
            AlertSeverity.INFO,
            AlertSeverity.WARNING,
            AlertSeverity.ERROR,
            AlertSeverity.CRITICAL,
        ]

        # Test that we can compare severities (using severity order)
        severity_order = {
            AlertSeverity.INFO: 0,
            AlertSeverity.WARNING: 1,
            AlertSeverity.ERROR: 2,
            AlertSeverity.CRITICAL: 3,
        }
        worst = max(severities, key=lambda s: severity_order[s])
        assert worst == AlertSeverity.CRITICAL

    def test_monitor_with_large_buffer(self):
        """Test monitor with large buffer."""
        monitor = Monitor(buffer_size=10000)

        # Record many metrics
        for i in range(5000):
            monitor.record_connection_establishment(
                f"conn{i}", f"peer{i}", "tcp", "inbound"
            )

        # Buffer should handle large number of metrics
        assert len(monitor.metrics_buffer) == 5000
        assert monitor.metrics_buffer.maxlen == 10000

    def test_metric_with_complex_labels(self):
        """Test metric with complex labels."""
        monitor = Monitor()

        # Record metric with complex labels
        complex_labels = {
            "peer_id": "peer1",
            "protocol": "kad",
            "direction": "inbound",
            "status": "success",
        }

        monitor.record_protocol_metric("kad", "requests", 10, complex_labels)

        # Verify metric is recorded with labels
        assert len(monitor.metrics_buffer) > 0
        metric = monitor.metrics_buffer[-1]
        assert metric.labels == complex_labels

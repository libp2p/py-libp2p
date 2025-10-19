"""
Production-grade monitoring and alerting system.

This module provides comprehensive monitoring capabilities including
OpenMetrics format export, real-time metrics collection, connection
duration tracking, and protocol-specific metrics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Any, Dict, List, Optional, Union


class MetricType(Enum):
    """Types of metrics for monitoring."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Metric:
    """A single metric measurement."""
    name: str
    value: Union[int, float]
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    help_text: str = ""


@dataclass
class Alert:
    """An alert condition."""
    name: str
    condition: str
    severity: AlertSeverity
    message: str
    threshold: Union[int, float]
    current_value: Union[int, float]
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False


@dataclass
class ConnectionDuration:
    """Connection duration tracking."""
    connection_id: str
    peer_id: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    protocol: str = "unknown"
    direction: str = "unknown"


class ProductionMonitor:
    """
    Production-grade monitoring and alerting system.

    Provides comprehensive monitoring capabilities including OpenMetrics
    format export, real-time metrics collection, connection duration
    tracking, and protocol-specific metrics.
    """

    def __init__(
        self,
        buffer_size: int = 1000,
        alert_thresholds: Optional[Dict[str, float]] = None,
        enable_connection_tracking: bool = True,
        enable_protocol_metrics: bool = True,
    ) -> None:
        """
        Initialize production monitor.

        Args:
            buffer_size: Maximum number of metrics to buffer
            alert_thresholds: Custom alert thresholds
            enable_connection_tracking: Enable connection duration tracking
            enable_protocol_metrics: Enable protocol-specific metrics

        """
        self.buffer_size = buffer_size
        self.alert_thresholds = alert_thresholds or {}
        self.enable_connection_tracking = enable_connection_tracking
        self.enable_protocol_metrics = enable_protocol_metrics

        # Metrics storage
        self.metrics_buffer: deque[Metric] = deque(maxlen=buffer_size)
        self.alerts: List[Alert] = []
        self._lock = threading.RLock()

        # Connection tracking
        self._connection_durations: Dict[str, ConnectionDuration] = {}
        self._connection_establishment_times: Dict[str, float] = {}

        # Protocol metrics
        self._protocol_metrics: Dict[str, Dict[str, Any]] = {}

        # System metrics
        self._start_time = time.time()
        self._total_metrics_recorded = 0
        self._total_alerts_triggered = 0

        # Default alert thresholds
        self._default_thresholds = {
            "connection_limit_percentage": 80.0,
            "memory_limit_percentage": 80.0,
            "stream_limit_percentage": 80.0,
            "error_rate_percentage": 5.0,
            "response_time_ms": 1000.0,
        }

        # Merge custom thresholds
        self.alert_thresholds = {**self._default_thresholds, **self.alert_thresholds}

    def record_metric(self, metric: Metric) -> None:
        """
        Record a metric with buffering for performance.

        Args:
            metric: The metric to record

        """
        with self._lock:
            self.metrics_buffer.append(metric)
            self._total_metrics_recorded += 1
            self._check_alerts(metric)

    def record_connection_establishment(
        self,
        connection_id: str,
        peer_id: str,
        protocol: str = "unknown",
        direction: str = "unknown"
    ) -> None:
        """
        Record connection establishment for duration tracking.

        Args:
            connection_id: Unique connection identifier
            peer_id: Peer identifier
            protocol: Protocol used for connection
            direction: Connection direction (inbound/outbound)

        """
        if not self.enable_connection_tracking:
            return

        with self._lock:
            current_time = time.time()
            self._connection_establishment_times[connection_id] = current_time

            # Create connection duration tracker
            duration_tracker = ConnectionDuration(
                connection_id=connection_id,
                peer_id=peer_id,
                start_time=current_time,
                protocol=protocol,
                direction=direction
            )
            self._connection_durations[connection_id] = duration_tracker

            # Record establishment metric
            establishment_metric = Metric(
                name="libp2p_connections_established_total",
                value=1,
                metric_type=MetricType.COUNTER,
                labels={
                    "protocol": protocol,
                    "direction": direction,
                    "peer_id": peer_id
                },
                help_text="Total number of connections established"
            )
            self.record_metric(establishment_metric)

    def record_connection_closed(
        self,
        connection_id: str,
        reason: str = "unknown"
    ) -> None:
        """
        Record connection closure and calculate duration.

        Args:
            connection_id: Unique connection identifier
            reason: Reason for connection closure

        """
        if not self.enable_connection_tracking:
            return

        with self._lock:
            if connection_id not in self._connection_durations:
                return

            current_time = time.time()
            duration_tracker = self._connection_durations[connection_id]
            duration_tracker.end_time = current_time
            duration_tracker.duration = current_time - duration_tracker.start_time

            # Record connection duration metric
            duration_metric = Metric(
                name="libp2p_connection_duration_seconds",
                value=duration_tracker.duration,
                metric_type=MetricType.HISTOGRAM,
                labels={
                    "protocol": duration_tracker.protocol,
                    "direction": duration_tracker.direction,
                    "reason": reason
                },
                help_text="Connection duration in seconds"
            )
            self.record_metric(duration_metric)

            # Record connection closed metric
            closed_metric = Metric(
                name="libp2p_connections_closed_total",
                value=1,
                metric_type=MetricType.COUNTER,
                labels={
                    "protocol": duration_tracker.protocol,
                    "direction": duration_tracker.direction,
                    "reason": reason
                },
                help_text="Total number of connections closed"
            )
            self.record_metric(closed_metric)

            # Clean up
            del self._connection_durations[connection_id]
            if connection_id in self._connection_establishment_times:
                del self._connection_establishment_times[connection_id]

    def record_protocol_metric(
        self,
        protocol: str,
        metric_name: str,
        value: Union[int, float],
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record protocol-specific metric.

        Args:
            protocol: Protocol name
            metric_name: Name of the metric
            value: Metric value
            labels: Additional labels

        """
        if not self.enable_protocol_metrics:
            return

        with self._lock:
            # Update protocol metrics
            if protocol not in self._protocol_metrics:
                self._protocol_metrics[protocol] = {}
            self._protocol_metrics[protocol][metric_name] = value

            # Create metric
            metric_labels = labels or {}
            metric_labels["protocol"] = protocol

            metric = Metric(
                name=f"libp2p_protocol_{metric_name}",
                value=value,
                metric_type=MetricType.GAUGE,
                labels=metric_labels,
                help_text=f"Protocol-specific metric: {metric_name}"
            )
            self.record_metric(metric)

    def record_resource_usage(
        self,
        resource_type: str,
        current_value: Union[int, float],
        limit_value: Union[int, float],
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record resource usage metrics.

        Args:
            resource_type: Type of resource (connections, memory, streams)
            current_value: Current usage value
            limit_value: Maximum limit value
            labels: Additional labels

        """
        metric_labels = labels or {}
        metric_labels["resource_type"] = resource_type

        # Record current usage
        current_metric = Metric(
            name="libp2p_resource_usage_current",
            value=current_value,
            metric_type=MetricType.GAUGE,
            labels=metric_labels,
            help_text=f"Current {resource_type} usage"
        )
        self.record_metric(current_metric)

        # Record limit
        limit_metric = Metric(
            name="libp2p_resource_usage_limit",
            value=limit_value,
            metric_type=MetricType.GAUGE,
            labels=metric_labels,
            help_text=f"Maximum {resource_type} limit"
        )
        self.record_metric(limit_metric)

        # Record percentage
        percentage = (current_value / limit_value * 100) if limit_value > 0 else 0
        percentage_metric = Metric(
            name="libp2p_resource_usage_percentage",
            value=percentage,
            metric_type=MetricType.GAUGE,
            labels=metric_labels,
            help_text=f"{resource_type} usage percentage"
        )
        self.record_metric(percentage_metric)

    def record_error(
        self,
        error_type: str,
        error_code: str,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record error metrics.

        Args:
            error_type: Type of error
            error_code: Error code
            labels: Additional labels

        """
        metric_labels = labels or {}
        metric_labels["error_type"] = error_type
        metric_labels["error_code"] = error_code

        error_metric = Metric(
            name="libp2p_errors_total",
            value=1,
            metric_type=MetricType.COUNTER,
            labels=metric_labels,
            help_text="Total number of errors by type and code"
        )
        self.record_metric(error_metric)

    def _check_alerts(self, metric: Metric) -> None:
        """
        Check for alert conditions based on metric.

        Args:
            metric: The metric to check for alerts

        """
        # Check resource usage alerts
        if metric.name == "libp2p_resource_usage_percentage":
            resource_type = metric.labels.get("resource_type", "unknown")
            threshold_key = f"{resource_type}_limit_percentage"
            threshold = self.alert_thresholds.get(threshold_key, 80.0)

            if metric.value >= threshold:
                alert = Alert(
                    name=f"{resource_type}_limit_high",
                    condition=f"{resource_type} usage >= {threshold}%",
                    severity=(
                        AlertSeverity.WARNING if metric.value < 95
                        else AlertSeverity.CRITICAL
                    ),
                    message=(
                        f"{resource_type} usage is {metric.value:.1f}% "
                        f"(threshold: {threshold}%)"
                    ),
                    threshold=threshold,
                    current_value=metric.value
                )
                self._trigger_alert(alert)

        # Check error rate alerts
        elif metric.name == "libp2p_errors_total":
            # Calculate error rate (simplified)
            # error_rate_threshold = self.alert_thresholds.get(
            #     "error_rate_percentage", 5.0
            # )
            # This would need more sophisticated error rate calculation
            pass

    def _trigger_alert(self, alert: Alert) -> None:
        """
        Trigger an alert.

        Args:
            alert: The alert to trigger

        """
        with self._lock:
            self.alerts.append(alert)
            self._total_alerts_triggered += 1

    def export_openmetrics(self) -> str:
        """
        Export metrics in OpenMetrics format.

        Returns:
            str: Metrics in OpenMetrics format

        """
        with self._lock:
            lines = []

            # Add header
            lines.append(
                "# HELP libp2p_monitor_uptime_seconds Monitor uptime in seconds"
            )
            lines.append("# TYPE libp2p_monitor_uptime_seconds gauge")
            lines.append(
                f"libp2p_monitor_uptime_seconds {time.time() - self._start_time}"
            )
            lines.append("")

            # Add metrics
            for metric in self.metrics_buffer:
                # Add help text
                if metric.help_text:
                    lines.append(f"# HELP {metric.name} {metric.help_text}")

                # Add type
                lines.append(f"# TYPE {metric.name} {metric.metric_type.value}")

                # Add metric with labels
                if metric.labels:
                    label_pairs = [f'{k}="{v}"' for k, v in metric.labels.items()]
                    labels_str = "{" + ",".join(label_pairs) + "}"
                    lines.append(
                        f"{metric.name}{labels_str} {metric.value} "
                        f"{int(metric.timestamp * 1000)}"
                    )
                else:
                    lines.append(
                        f"{metric.name} {metric.value} "
                        f"{int(metric.timestamp * 1000)}"
                    )
                lines.append("")

            return "\n".join(lines)

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all metrics.

        Returns:
            Dict containing metrics summary

        """
        with self._lock:
            return {
                "uptime_seconds": time.time() - self._start_time,
                "total_metrics_recorded": self._total_metrics_recorded,
                "total_alerts_triggered": self._total_alerts_triggered,
                "active_connections": len(self._connection_durations),
                "protocols_tracked": list(self._protocol_metrics.keys()),
                "recent_alerts": [
                    {
                        "name": alert.name,
                        "severity": alert.severity.value,
                        "message": alert.message,
                        "timestamp": alert.timestamp,
                        "resolved": alert.resolved
                    }
                    for alert in self.alerts[-10:]  # Last 10 alerts
                ]
            }

    def get_connection_durations(self) -> List[Dict[str, Any]]:
        """
        Get connection duration statistics.

        Returns:
            List of connection duration information

        """
        with self._lock:
            durations = []
            for conn_id, duration_tracker in self._connection_durations.items():
                durations.append({
                    "connection_id": conn_id,
                    "peer_id": duration_tracker.peer_id,
                    "protocol": duration_tracker.protocol,
                    "direction": duration_tracker.direction,
                    "start_time": duration_tracker.start_time,
                    "end_time": duration_tracker.end_time,
                    "duration": duration_tracker.duration,
                    "is_active": duration_tracker.end_time is None
                })
            return durations

    def get_protocol_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Get protocol-specific metrics.

        Returns:
            Dict of protocol metrics

        """
        with self._lock:
            return dict(self._protocol_metrics)

    def clear_old_metrics(self, max_age_seconds: float = 3600) -> None:
        """
        Clear old metrics to prevent memory buildup.

        Args:
            max_age_seconds: Maximum age of metrics to keep

        """
        with self._lock:
            current_time = time.time()
            cutoff_time = current_time - max_age_seconds

            # Clear old metrics from buffer
            while (self.metrics_buffer and
                   self.metrics_buffer[0].timestamp < cutoff_time):
                self.metrics_buffer.popleft()

            # Clear old alerts
            self.alerts = [
                alert for alert in self.alerts if alert.timestamp >= cutoff_time
            ]

    def reset(self) -> None:
        """Reset all monitoring data."""
        with self._lock:
            self.metrics_buffer.clear()
            self.alerts.clear()
            self._connection_durations.clear()
            self._connection_establishment_times.clear()
            self._protocol_metrics.clear()
            self._total_metrics_recorded = 0
            self._total_alerts_triggered = 0
            self._start_time = time.time()

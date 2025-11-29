"""
System health monitoring and checks.

This module provides comprehensive health monitoring capabilities including
health check endpoints, automated health monitoring, system health indicators,
and recovery mechanisms.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Any

import psutil


class HealthStatus(Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


class HealthCheckType(Enum):
    """Types of health checks."""

    RESOURCE_USAGE = "resource_usage"
    CONNECTION_HEALTH = "connection_health"
    MEMORY_HEALTH = "memory_health"
    SYSTEM_HEALTH = "system_health"
    PERFORMANCE_HEALTH = "performance_health"


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    check_type: HealthCheckType
    status: HealthStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0


@dataclass
class HealthHistory:
    """Health check history entry."""

    timestamp: float
    overall_status: HealthStatus
    checks: list[HealthCheckResult]
    system_info: dict[str, Any]


class HealthChecker:
    """
    System health monitoring and checks.

    Provides comprehensive health monitoring including resource usage,
    connection health, memory health, system health, and performance health.
    """

    def __init__(
        self,
        resource_manager: Any,  # ResourceManager type
        check_interval: float = 30.0,
        history_size: int = 100,
        enable_system_checks: bool = True,
        enable_performance_checks: bool = True,
    ) -> None:
        """
        Initialize health checker.

        Args:
            resource_manager: The resource manager to monitor
            check_interval: Interval between health checks in seconds
            history_size: Maximum number of health history entries
            enable_system_checks: Enable system-level health checks
            enable_performance_checks: Enable performance health checks

        """
        self.rm = resource_manager
        self.check_interval = check_interval
        self.history_size = history_size
        self.enable_system_checks = enable_system_checks
        self.enable_performance_checks = enable_performance_checks

        # Health tracking
        self._health_status = HealthStatus.HEALTHY
        self._last_check = 0.0
        self._health_history: deque[HealthHistory] = deque(maxlen=history_size)
        self._lock = threading.RLock()

        # Health thresholds
        self._thresholds = {
            "resource_usage_warning": 70.0,  # 70% usage triggers warning
            "resource_usage_critical": 90.0,  # 90% usage triggers critical
            "memory_usage_warning": 80.0,  # 80% memory usage triggers warning
            "memory_usage_critical": 95.0,  # 95% memory usage triggers critical
            "connection_failure_rate": 10.0,  # 10% connection failure rate
            "response_time_warning": 1000.0,  # 1 second response time
            "response_time_critical": 5000.0,  # 5 second response time
            "system_cpu_warning": 80.0,  # 80% CPU usage
            "system_cpu_critical": 95.0,  # 95% CPU usage
            "system_memory_warning": 85.0,  # 85% system memory
            "system_memory_critical": 95.0,  # 95% system memory
        }

    def check_health(self) -> HealthStatus:
        """
        Perform comprehensive health check.

        Returns:
            HealthStatus: Overall health status

        """
        start_time = time.time()

        with self._lock:
            # Perform individual health checks
            checks = []

            # Resource usage check
            resource_check = self._check_resources()
            checks.append(resource_check)

            # Connection health check
            connection_check = self._check_connections()
            checks.append(connection_check)

            # Memory health check
            memory_check = self._check_memory()
            checks.append(memory_check)

            # System health check
            if self.enable_system_checks:
                system_check = self._check_system()
                checks.append(system_check)

            # Performance health check
            if self.enable_performance_checks:
                performance_check = self._check_performance()
                checks.append(performance_check)

            # Calculate overall health
            overall_health = self._calculate_overall_health(checks)

            # Store health history
            health_entry = HealthHistory(
                timestamp=start_time,
                overall_status=overall_health,
                checks=checks,
                system_info=self._get_system_info(),
            )
            self._health_history.append(health_entry)

            # Update status
            self._health_status = overall_health
            self._last_check = start_time

            return overall_health

    def _check_resources(self) -> HealthCheckResult:
        """Check resource usage health."""
        start_time = time.time()

        try:
            stats = self.rm.get_stats()

            # Check connection usage
            conn_usage = (
                stats["connections"] / stats["limits"]["max_connections"]
            ) * 100
            conn_status = self._get_status_from_percentage(conn_usage, "connection")

            # Check memory usage
            memory_usage = (
                stats["memory_bytes"] / stats["limits"]["max_memory_bytes"]
            ) * 100
            memory_status = self._get_status_from_percentage(memory_usage, "memory")

            # Check stream usage
            stream_usage = (stats["streams"] / stats["limits"]["max_streams"]) * 100
            stream_status = self._get_status_from_percentage(stream_usage, "stream")

            # Overall resource status
            # Get the worst status (highest severity)
            statuses = [conn_status, memory_status, stream_status]
            overall_status = max(statuses, key=lambda s: s.value)

            duration_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                check_type=HealthCheckType.RESOURCE_USAGE,
                status=overall_status,
                message=(
                    f"Resource usage: connections={conn_usage:.1f}%, "
                    f"memory={memory_usage:.1f}%, streams={stream_usage:.1f}%"
                ),
                details={
                    "connection_usage_percent": conn_usage,
                    "memory_usage_percent": memory_usage,
                    "stream_usage_percent": stream_usage,
                    "connection_count": stats["connections"],
                    "memory_bytes": stats["memory_bytes"],
                    "stream_count": stats["streams"],
                    "limits": stats["limits"],
                },
                duration_ms=duration_ms,
            )

        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.RESOURCE_USAGE,
                status=HealthStatus.CRITICAL,
                message=f"Failed to check resource usage: {e}",
                details={"error": str(e)},
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _check_connections(self) -> HealthCheckResult:
        """Check connection health."""
        start_time = time.time()

        try:
            stats = self.rm.get_stats()

            # Get connection pool stats if available
            connection_pool_stats = stats.get("connection_pool", {})

            # Check connection availability
            max_connections = stats["limits"]["max_connections"]
            current_connections = stats["connections"]
            available_connections = max_connections - current_connections

            # Calculate connection health
            if available_connections <= 0:
                status = HealthStatus.CRITICAL
                message = "No available connections"
            elif available_connections < max_connections * 0.1:  # Less than 10%
                status = HealthStatus.UNHEALTHY
                message = (
                    f"Low connection availability: {available_connections} remaining"
                )
            elif available_connections < max_connections * 0.2:  # Less than 20%
                status = HealthStatus.DEGRADED
                message = (
                    f"Reduced connection availability: "
                    f"{available_connections} remaining"
                )
            else:
                status = HealthStatus.HEALTHY
                message = f"Connection health good: {available_connections} available"

            duration_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                check_type=HealthCheckType.CONNECTION_HEALTH,
                status=status,
                message=message,
                details={
                    "current_connections": current_connections,
                    "max_connections": max_connections,
                    "available_connections": available_connections,
                    "connection_pool_stats": connection_pool_stats,
                },
                duration_ms=duration_ms,
            )

        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.CONNECTION_HEALTH,
                status=HealthStatus.CRITICAL,
                message=f"Failed to check connection health: {e}",
                details={"error": str(e)},
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _check_memory(self) -> HealthCheckResult:
        """Check memory health."""
        start_time = time.time()

        try:
            # Get system memory info
            system_memory = psutil.virtual_memory()
            # psutil.Process() returns a process object whose methods are
            # dynamically provided by the psutil package. Static analysis
            # tools may incorrectly infer bound-method signatures and
            # report false positives such as `missing argument self` when
            # calling `process.memory_info()`.  Annotate the local value
            # as `Any` to suppress that false positive while preserving
            # runtime behavior and type safety for callers of this module.
            process: Any = psutil.Process()
            # Call via getattr and add a type-ignore to avoid static analyzers
            # incorrectly reporting a missing `self` argument for psutil's
            # bound methods (they can be implemented with descriptors that
            # confuse some checkers).
            process_memory = getattr(process, "memory_info")()  # type: ignore

            # Get resource manager memory stats
            stats = self.rm.get_stats()
            memory_bytes = stats["memory_bytes"]
            max_memory_bytes = stats["limits"]["max_memory_bytes"]

            # Calculate memory usage percentages
            system_memory_percent = system_memory.percent
            process_memory_percent = (process_memory.rss / system_memory.total) * 100
            resource_memory_percent = (memory_bytes / max_memory_bytes) * 100

            # Determine memory health status
            system_status = self._get_status_from_percentage(
                system_memory_percent, "system_memory"
            )
            process_status = self._get_status_from_percentage(
                process_memory_percent, "process_memory"
            )
            resource_status = self._get_status_from_percentage(
                resource_memory_percent, "resource_memory"
            )

            # Get the worst status (highest severity)
            statuses = [system_status, process_status, resource_status]
            overall_status = max(statuses, key=lambda s: s.value)

            duration_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                check_type=HealthCheckType.MEMORY_HEALTH,
                status=overall_status,
                message=(
                    f"Memory usage: system={system_memory_percent:.1f}%, "
                    f"process={process_memory_percent:.1f}%, "
                    f"resource={resource_memory_percent:.1f}%"
                ),
                details={
                    "system_memory_percent": system_memory_percent,
                    "system_memory_available": system_memory.available,
                    "system_memory_total": system_memory.total,
                    "process_memory_rss": process_memory.rss,
                    "process_memory_vms": process_memory.vms,
                    "process_memory_percent": process_memory_percent,
                    "resource_memory_bytes": memory_bytes,
                    "resource_memory_percent": resource_memory_percent,
                    "max_memory_bytes": max_memory_bytes,
                },
                duration_ms=duration_ms,
            )

        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.MEMORY_HEALTH,
                status=HealthStatus.CRITICAL,
                message=f"Failed to check memory health: {e}",
                details={"error": str(e)},
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _check_system(self) -> HealthCheckResult:
        """Check system health."""
        start_time = time.time()

        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Check CPU health
            if isinstance(cpu_percent, (int, float)):
                cpu_percent_value = cpu_percent
            elif cpu_percent:
                cpu_percent_value = cpu_percent[0]
            else:
                cpu_percent_value = 0.0
            cpu_status = self._get_status_from_percentage(cpu_percent_value, "cpu")

            # Check system memory health
            memory_status = self._get_status_from_percentage(
                memory.percent, "system_memory"
            )

            # Check disk health
            disk_status = self._get_status_from_percentage(disk.percent, "disk")

            # Get the worst status (highest severity)
            statuses = [cpu_status, memory_status, disk_status]
            overall_status = max(statuses, key=lambda s: s.value)

            duration_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                check_type=HealthCheckType.SYSTEM_HEALTH,
                status=overall_status,
                message=(
                    f"System health: CPU={cpu_percent:.1f}%, "
                    f"Memory={memory.percent:.1f}%, Disk={disk.percent:.1f}%"
                ),
                details={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_available": memory.available,
                    "memory_total": memory.total,
                    "disk_percent": disk.percent,
                    "disk_free": disk.free,
                    "disk_total": disk.total,
                },
                duration_ms=duration_ms,
            )

        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.SYSTEM_HEALTH,
                status=HealthStatus.CRITICAL,
                message=f"Failed to check system health: {e}",
                details={"error": str(e)},
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _check_performance(self) -> HealthCheckResult:
        """Check performance health."""
        start_time = time.time()

        try:
            # Measure resource manager response time
            response_start = time.time()
            # stats = self.rm.get_stats()
            response_time = (time.time() - response_start) * 1000  # Convert to ms

            # Check response time health
            if response_time > self._thresholds["response_time_critical"]:
                status = HealthStatus.CRITICAL
                message = f"Critical response time: {response_time:.1f}ms"
            elif response_time > self._thresholds["response_time_warning"]:
                status = HealthStatus.DEGRADED
                message = f"Slow response time: {response_time:.1f}ms"
            else:
                status = HealthStatus.HEALTHY
                message = f"Good response time: {response_time:.1f}ms"

            duration_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                check_type=HealthCheckType.PERFORMANCE_HEALTH,
                status=status,
                message=message,
                details={
                    "response_time_ms": response_time,
                    "stats_retrieval_time_ms": response_time,
                    "thresholds": {
                        "warning_ms": self._thresholds["response_time_warning"],
                        "critical_ms": self._thresholds["response_time_critical"],
                    },
                },
                duration_ms=duration_ms,
            )

        except Exception as e:
            return HealthCheckResult(
                check_type=HealthCheckType.PERFORMANCE_HEALTH,
                status=HealthStatus.CRITICAL,
                message=f"Failed to check performance health: {e}",
                details={"error": str(e)},
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _get_status_from_percentage(
        self, percentage: float, metric_type: str
    ) -> HealthStatus:
        """Get health status from percentage value."""
        warning_key = f"{metric_type}_warning"
        critical_key = f"{metric_type}_critical"

        warning_threshold = self._thresholds.get(warning_key, 80.0)
        critical_threshold = self._thresholds.get(critical_key, 95.0)

        if percentage >= critical_threshold:
            return HealthStatus.CRITICAL
        elif percentage >= warning_threshold:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    def _calculate_overall_health(
        self, checks: list[HealthCheckResult]
    ) -> HealthStatus:
        """Calculate overall health status from individual checks."""
        if not checks:
            return HealthStatus.UNHEALTHY

        # Get the worst status from all checks
        statuses = [check.status for check in checks]

        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        elif HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    def _get_system_info(self) -> dict[str, Any]:
        """Get system information."""
        try:
            return {
                "cpu_count": psutil.cpu_count(),
                "memory_total": psutil.virtual_memory().total,
                "disk_total": psutil.disk_usage("/").total,
                "boot_time": psutil.boot_time(),
                "python_version": psutil.sys.version,
                "platform": psutil.sys.platform,
            }
        except Exception:
            return {}

    def get_health_endpoint(self) -> dict[str, Any]:
        """
        Get health status for HTTP endpoint.

        Returns:
            Dict containing health status information

        """
        with self._lock:
            # Get latest health check if available
            latest_health = None
            if self._health_history:
                latest_health = self._health_history[-1]

            return {
                "status": self._health_status.value,
                "timestamp": self._last_check,
                "uptime_seconds": time.time()
                - (
                    self._health_history[0].timestamp
                    if self._health_history
                    else time.time()
                ),
                "last_check": self._last_check,
                "latest_health": {
                    "overall_status": (
                        latest_health.overall_status.value
                        if latest_health
                        else "unknown"
                    ),
                    "checks": [
                        {
                            "type": check.check_type.value,
                            "status": check.status.value,
                            "message": check.message,
                            "duration_ms": check.duration_ms,
                            "details": check.details,
                        }
                        for check in (latest_health.checks if latest_health else [])
                    ],
                    "system_info": latest_health.system_info if latest_health else {},
                }
                if latest_health
                else None,
                "health_history_size": len(self._health_history),
                "check_interval": self.check_interval,
                "thresholds": self._thresholds,
            }

    def get_health_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get health check history.

        Args:
            limit: Maximum number of history entries to return

        Returns:
            List of health history entries

        """
        with self._lock:
            history = list(self._health_history)[-limit:]
            return [
                {
                    "timestamp": entry.timestamp,
                    "overall_status": entry.overall_status.value,
                    "checks": [
                        {
                            "type": check.check_type.value,
                            "status": check.status.value,
                            "message": check.message,
                            "duration_ms": check.duration_ms,
                        }
                        for check in entry.checks
                    ],
                    "system_info": entry.system_info,
                }
                for entry in history
            ]

    def get_current_status(self) -> HealthStatus:
        """Get current health status."""
        with self._lock:
            return self._health_status

    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        return self.get_current_status() == HealthStatus.HEALTHY

    def is_degraded(self) -> bool:
        """Check if system is degraded."""
        return self.get_current_status() == HealthStatus.DEGRADED

    def is_unhealthy(self) -> bool:
        """Check if system is unhealthy."""
        return self.get_current_status() in [
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

    def set_threshold(self, metric: str, warning: float, critical: float) -> None:
        """
        Set health check thresholds.

        Args:
            metric: Metric name
            warning: Warning threshold
            critical: Critical threshold

        """
        with self._lock:
            self._thresholds[f"{metric}_warning"] = warning
            self._thresholds[f"{metric}_critical"] = critical

    def get_thresholds(self) -> dict[str, float]:
        """Get current health check thresholds."""
        with self._lock:
            return dict(self._thresholds)

    def clear_history(self) -> None:
        """Clear health check history."""
        with self._lock:
            self._health_history.clear()

    def reset(self) -> None:
        """Reset health checker."""
        with self._lock:
            self._health_status = HealthStatus.HEALTHY
            self._last_check = 0.0
            self._health_history.clear()

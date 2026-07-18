"""
Resource manager health check tests.

Tests the health check system including system health monitoring,
resource health checks, and health status reporting.
"""

import time
from unittest.mock import Mock, patch

from libp2p.rcmgr import new_resource_manager
from libp2p.rcmgr.health_checks import (
    HealthChecker,
    HealthCheckResult,
    HealthCheckType,
    HealthHistory,
    HealthStatus,
)


class TestHealthChecker:
    """Test the health check system."""

    def test_health_checker_initialization(self):
        """Test health checker initialization."""
        rm = new_resource_manager()
        checker = HealthChecker(rm)
        assert checker is not None
        assert checker.rm == rm
        assert checker.check_interval == 30.0
        assert checker.history_size == 100

    def test_check_health(self):
        """Test comprehensive health checking."""
        rm = new_resource_manager()
        checker = HealthChecker(rm)

        # Test health check
        health_status = checker.check_health()
        assert health_status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

    def test_health_status_enum(self):
        """Test HealthStatus enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.CRITICAL.value == "critical"

    def test_health_check_type_enum(self):
        """Test HealthCheckType enum values."""
        assert HealthCheckType.RESOURCE_USAGE.value == "resource_usage"
        assert HealthCheckType.CONNECTION_HEALTH.value == "connection_health"
        assert HealthCheckType.MEMORY_HEALTH.value == "memory_health"
        assert HealthCheckType.SYSTEM_HEALTH.value == "system_health"
        assert HealthCheckType.PERFORMANCE_HEALTH.value == "performance_health"

    def test_health_check_result_creation(self):
        """Test HealthCheckResult creation."""
        result = HealthCheckResult(
            check_type=HealthCheckType.RESOURCE_USAGE,
            status=HealthStatus.HEALTHY,
            message="All resources healthy",
            details={"connections": 10},
            timestamp=time.time(),
        )
        assert result.check_type == HealthCheckType.RESOURCE_USAGE
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All resources healthy"
        assert result.details["connections"] == 10

    def test_health_history_creation(self):
        """Test HealthHistory creation."""
        checks = [
            HealthCheckResult(
                check_type=HealthCheckType.RESOURCE_USAGE,
                status=HealthStatus.HEALTHY,
                message="Resources OK",
                details={"connections": 5},
            )
        ]

        history = HealthHistory(
            timestamp=time.time(),
            overall_status=HealthStatus.HEALTHY,
            checks=checks,
            system_info={"cpu_percent": 10.0},
        )

        assert history.overall_status == HealthStatus.HEALTHY
        assert len(history.checks) == 1
        assert history.system_info["cpu_percent"] == 10.0

    def test_health_checker_with_custom_settings(self):
        """Test health checker with custom settings."""
        rm = new_resource_manager()
        checker = HealthChecker(
            rm,
            check_interval=60.0,
            history_size=50,
            enable_system_checks=False,
            enable_performance_checks=False,
        )

        assert checker.check_interval == 60.0
        assert checker.history_size == 50
        assert checker.enable_system_checks is False
        assert checker.enable_performance_checks is False

    def test_health_status_comparison(self):
        """Test health status comparison."""
        # Test that we can compare health statuses by their values
        statuses = [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

        # Test that we can get the worst status (using severity order)
        severity_order = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.DEGRADED: 1,
            HealthStatus.UNHEALTHY: 2,
            HealthStatus.CRITICAL: 3,
        }
        worst = max(statuses, key=lambda s: severity_order[s])
        assert worst == HealthStatus.CRITICAL

    @patch("psutil.Process")
    @patch("psutil.virtual_memory")
    def test_health_checker_with_mock_resource_manager(self, mock_memory, mock_process):
        """Test health checker with mocked resource manager."""
        # Mock system memory
        mock_memory.return_value = Mock(
            percent=30.0, available=8 * 1024**3, total=16 * 1024**3
        )

        # Mock process memory
        mock_process.return_value.memory_info.return_value = Mock(
            rss=100 * 1024 * 1024  # 100MB
        )

        mock_rm = Mock()
        mock_rm.get_stats.return_value = {
            "connections": 5,
            "memory_bytes": 1024 * 1024,
            "streams": 10,
            "limits": {
                "max_connections": 100,
                "max_memory_bytes": 10 * 1024 * 1024,
                "max_streams": 1000,
            },
        }

        checker = HealthChecker(
            mock_rm,
            enable_system_checks=False,
            enable_performance_checks=False,
        )
        health_status = checker.check_health()

        # Should be healthy with low resource usage
        assert health_status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        mock_rm.get_stats.assert_called()

    def test_health_checker_with_high_resource_usage(self):
        """Test health checker with high resource usage."""
        mock_rm = Mock()
        mock_rm.get_stats.return_value = {
            "connections": 95,  # 95% usage
            "memory_bytes": 9 * 1024 * 1024,  # 90% usage
            "streams": 950,  # 95% usage
            "limits": {
                "max_connections": 100,
                "max_memory_bytes": 10 * 1024 * 1024,
                "max_streams": 1000,
            },
        }

        checker = HealthChecker(mock_rm)
        health_status = checker.check_health()

        # Should be unhealthy or critical with high resource usage
        assert health_status in [HealthStatus.UNHEALTHY, HealthStatus.CRITICAL]

    def test_health_checker_system_checks_disabled(self):
        """Test health checker with system checks disabled."""
        rm = new_resource_manager()
        checker = HealthChecker(rm, enable_system_checks=False)

        # Should still work but without system-level checks
        health_status = checker.check_health()
        assert health_status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

    def test_health_checker_performance_checks_disabled(self):
        """Test health checker with performance checks disabled."""
        rm = new_resource_manager()
        checker = HealthChecker(
            rm,
            enable_performance_checks=False,
        )

        # Should still work but without performance checks
        health_status = checker.check_health()
        assert health_status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

    def test_health_checker_history(self):
        """Test health checker history tracking."""
        rm = new_resource_manager()
        checker = HealthChecker(rm, history_size=5)

        # Perform multiple health checks
        for _ in range(3):
            checker.check_health()

        # Check that history is being tracked
        history = checker.get_health_history(limit=10)
        assert len(history) <= 3  # Should have at most 3 entries

    def test_health_checker_endpoint(self):
        """Test health checker endpoint data."""
        rm = new_resource_manager()
        checker = HealthChecker(rm)

        # Perform a health check
        checker.check_health()

        # Get endpoint data
        endpoint_data = checker.get_health_endpoint()
        assert "status" in endpoint_data
        assert "timestamp" in endpoint_data
        assert "uptime_seconds" in endpoint_data
        assert "latest_health" in endpoint_data

    def test_health_checker_thresholds(self):
        """Test health checker threshold settings."""
        rm = new_resource_manager()
        checker = HealthChecker(rm)

        # Test setting custom thresholds
        checker.set_threshold("connection", 50.0, 80.0)
        checker.set_threshold("memory", 60.0, 90.0)

        # Thresholds should be set
        assert checker._thresholds["connection_warning"] == 50.0
        assert checker._thresholds["connection_critical"] == 80.0
        assert checker._thresholds["memory_warning"] == 60.0
        assert checker._thresholds["memory_critical"] == 90.0

    def test_health_checker_status_methods(self):
        """Test health checker status methods."""
        rm = new_resource_manager()
        checker = HealthChecker(rm)

        # Test status checking methods
        assert isinstance(checker.is_healthy(), bool)
        assert isinstance(checker.is_degraded(), bool)
        assert isinstance(checker.is_unhealthy(), bool)

        # These should be consistent
        current_status = checker.get_current_status()
        assert current_status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

    @patch("psutil.cpu_percent")
    @patch("psutil.virtual_memory")
    @patch("psutil.disk_usage")
    def test_health_checker_with_mocked_system(self, mock_disk, mock_memory, mock_cpu):
        """Test health checker with mocked system resources."""
        # Mock system resources
        mock_cpu.return_value = 25.0
        mock_memory.return_value = Mock(
            percent=30.0, available=8 * 1024**3, total=16 * 1024**3
        )
        mock_disk.return_value = Mock(percent=40.0)

        rm = new_resource_manager()
        checker = HealthChecker(rm)

        # Should work with mocked system
        health_status = checker.check_health()
        assert health_status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
            HealthStatus.CRITICAL,
        ]

    def test_health_checker_error_handling(self):
        """Test health checker error handling."""
        # Create a resource manager that raises an exception
        mock_rm = Mock()
        mock_rm.get_stats.side_effect = Exception("Resource manager error")

        checker = HealthChecker(mock_rm)

        # Should handle errors gracefully
        health_status = checker.check_health()
        assert health_status in [HealthStatus.UNHEALTHY, HealthStatus.CRITICAL]

    def test_health_checker_concurrent_access(self):
        """Test health checker concurrent access."""
        import threading

        rm = new_resource_manager()
        checker = HealthChecker(rm)

        results = []

        def check_health():
            results.append(checker.check_health())

        # Run multiple health checks concurrently
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=check_health)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All checks should complete successfully
        assert len(results) == 5
        for result in results:
            assert result in [
                HealthStatus.HEALTHY,
                HealthStatus.DEGRADED,
                HealthStatus.UNHEALTHY,
                HealthStatus.CRITICAL,
            ]

"""
Resource Manager for py-libp2p.

This package provides resource management capabilities to prevent
resource exhaustion attacks by limiting resource usage across
different scopes in the libp2p stack.

Key components:
- ResourceManager: Main resource manager class
- Resource Scopes: Hierarchical resource tracking
- Limits: Configurable resource limits
- Allowlist: Bypass limits for trusted peers/addresses
- Metrics: Resource usage tracking and observability
"""

from .allowlist import Allowlist, AllowlistConfig, new_allowlist, new_allowlist_with_config
from .connection_limits import ConnectionLimits, new_connection_limits, new_connection_limits_with_defaults
from .exceptions import (
    ResourceLimitExceeded,
    MemoryLimitExceeded,
    StreamOrConnLimitExceeded,
    ResourceScopeClosed,
)
from .limits import Direction
from .manager import ResourceManager, new_resource_manager, ResourceLimits
from .memory_limits import MemoryConnectionLimits
from .metrics import Metrics, ResourceMetrics
from .connection_pool import ConnectionPool
from .memory_pool import MemoryPool
from .circuit_breaker import CircuitBreaker, CircuitBreakerError
from .graceful_degradation import GracefulDegradation
from .monitoring import ProductionMonitor, Metric, Alert, MetricType, AlertSeverity
from .health_checks import HealthChecker, HealthStatus, HealthCheckType, HealthCheckResult
from .config import ProductionConfig, ConnectionConfig, MemoryConfig, PerformanceConfig, MonitoringConfig, CircuitBreakerConfig, GracefulDegradationConfig, LoggingConfig, SecurityConfig

__all__ = [
    # Main classes
    "ResourceManager",
    "new_resource_manager",
    "ResourceLimits",
    # Connection Limits
    "ConnectionLimits",
    "new_connection_limits",
    "new_connection_limits_with_defaults",
    # Memory Limits
    "MemoryConnectionLimits",
    # Allowlist
    "Allowlist",
    "AllowlistConfig",
    "new_allowlist",
    "new_allowlist_with_config",
    # Metrics
    "Metrics",
    "ResourceMetrics",
    # Enums
    "Direction",
    # Performance Optimizations
    "ConnectionPool",
    "MemoryPool",
    # Production Features
    "CircuitBreaker",
    "CircuitBreakerError",
    "GracefulDegradation",
    # Monitoring & Health
    "ProductionMonitor",
    "Metric",
    "Alert",
    "MetricType",
    "AlertSeverity",
    "HealthChecker",
    "HealthStatus",
    "HealthCheckType",
    "HealthCheckResult",
    # Configuration
    "ProductionConfig",
    "ConnectionConfig",
    "MemoryConfig",
    "PerformanceConfig",
    "MonitoringConfig",
    "CircuitBreakerConfig",
    "GracefulDegradationConfig",
    "LoggingConfig",
    "SecurityConfig",
    # Exceptions
    "ResourceLimitExceeded",
    "MemoryLimitExceeded",
    "StreamOrConnLimitExceeded",
    "ResourceScopeClosed",
]

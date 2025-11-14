"""
Production-optimized configuration system.

This module provides comprehensive configuration management including
environment-based configuration, production tuning options, and
deployment configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any


@dataclass
class ConnectionConfig:
    """Connection-related configuration."""

    max_connections: int = 10000
    max_connections_per_peer: int = 50
    connection_timeout: float = 30.0
    connection_keepalive: float = 60.0
    connection_retry_attempts: int = 3
    connection_retry_delay: float = 1.0


@dataclass
class MemoryConfig:
    """Memory-related configuration."""

    max_memory_mb: int = 1024
    memory_pool_size: int = 1000
    memory_pool_block_size: int = 1024 * 1024  # 1MB blocks
    memory_cleanup_interval: float = 300.0  # 5 minutes
    memory_monitoring_interval: float = 10.0  # 10 seconds


@dataclass
class PerformanceConfig:
    """Performance-related configuration."""

    enable_connection_pooling: bool = True
    enable_memory_pooling: bool = True
    enable_lockfree_structures: bool = True
    enable_preallocation: bool = True
    max_concurrent_operations: int = 1000
    operation_timeout: float = 5.0


@dataclass
class MonitoringConfig:
    """Monitoring-related configuration."""

    enable_metrics: bool = True
    enable_health_checks: bool = True
    metrics_buffer_size: int = 1000
    health_check_interval: float = 30.0
    health_check_timeout: float = 5.0
    alert_thresholds: dict[str, float] = field(default_factory=dict)
    enable_openmetrics_export: bool = True
    enable_prometheus_integration: bool = True


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    enabled: bool = True
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    failure_rate_threshold: float = 50.0
    slow_call_duration_threshold: float = 2.0
    slow_call_rate_threshold: float = 50.0


@dataclass
class GracefulDegradationConfig:
    """Graceful degradation configuration."""

    enabled: bool = True
    max_degradation_levels: int = 5
    degradation_factor: float = 0.2
    recovery_factor: float = 0.1
    degradation_cooldown: float = 300.0  # 5 minutes
    auto_recovery: bool = True


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    enable_structured_logging: bool = True
    enable_json_logging: bool = False
    log_file: str | None = None
    max_log_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


@dataclass
class SecurityConfig:
    """Security-related configuration."""

    enable_rate_limiting: bool = True
    max_requests_per_second: float = 100.0
    enable_allowlist: bool = True
    enable_blocklist: bool = True
    max_peer_connections: int = 10
    connection_rate_limit: float = 10.0


@dataclass
class ProductionConfig:
    """
    Production-optimized configuration.

    This configuration class provides comprehensive settings for
    production deployment of the resource manager.
    """

    # Core configuration sections
    connections: ConnectionConfig = field(default_factory=ConnectionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    graceful_degradation: GracefulDegradationConfig = field(
        default_factory=GracefulDegradationConfig
    )
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # Global settings
    environment: str = "production"
    debug: bool = False
    profile: bool = False
    version: str = "1.0.0"

    # Deployment settings
    deployment_id: str | None = None
    region: str | None = None
    cluster: str | None = None
    node_id: str | None = None

    def __post_init__(self) -> None:
        """Post-initialization setup."""
        # Set default alert thresholds if not provided
        if not self.monitoring.alert_thresholds:
            self.monitoring.alert_thresholds = {
                "connection_limit_percentage": 80.0,
                "memory_limit_percentage": 80.0,
                "stream_limit_percentage": 80.0,
                "error_rate_percentage": 5.0,
                "response_time_ms": 1000.0,
                "system_cpu_percentage": 80.0,
                "system_memory_percentage": 85.0,
            }

        # Set deployment ID if not provided
        if not self.deployment_id:
            self.deployment_id = os.getenv("DEPLOYMENT_ID", "default")

        # Set node ID if not provided
        if not self.node_id:
            self.node_id = os.getenv("NODE_ID", "node-1")

    @classmethod
    def from_env(cls) -> ProductionConfig:
        """
        Load configuration from environment variables.

        Returns:
            ProductionConfig: Configuration loaded from environment

        """
        # Connection settings
        connections = ConnectionConfig(
            max_connections=int(os.getenv("MAX_CONNECTIONS", "10000")),
            max_connections_per_peer=int(os.getenv("MAX_CONNECTIONS_PER_PEER", "50")),
            connection_timeout=float(os.getenv("CONNECTION_TIMEOUT", "30.0")),
            connection_keepalive=float(os.getenv("CONNECTION_KEEPALIVE", "60.0")),
            connection_retry_attempts=int(os.getenv("CONNECTION_RETRY_ATTEMPTS", "3")),
            connection_retry_delay=float(os.getenv("CONNECTION_RETRY_DELAY", "1.0")),
        )

        # Memory settings
        memory = MemoryConfig(
            max_memory_mb=int(os.getenv("MAX_MEMORY_MB", "1024")),
            memory_pool_size=int(os.getenv("MEMORY_POOL_SIZE", "1000")),
            memory_pool_block_size=int(
                os.getenv("MEMORY_POOL_BLOCK_SIZE", str(1024 * 1024))
            ),
            memory_cleanup_interval=float(
                os.getenv("MEMORY_CLEANUP_INTERVAL", "300.0")
            ),
            memory_monitoring_interval=float(
                os.getenv("MEMORY_MONITORING_INTERVAL", "10.0")
            ),
        )

        # Performance settings
        performance = PerformanceConfig(
            enable_connection_pooling=os.getenv(
                "ENABLE_CONNECTION_POOLING", "true"
            ).lower()
            == "true",
            enable_memory_pooling=os.getenv("ENABLE_MEMORY_POOLING", "true").lower()
            == "true",
            enable_lockfree_structures=os.getenv(
                "ENABLE_LOCKFREE_STRUCTURES", "true"
            ).lower()
            == "true",
            enable_preallocation=os.getenv("ENABLE_PREALLOCATION", "true").lower()
            == "true",
            max_concurrent_operations=int(
                os.getenv("MAX_CONCURRENT_OPERATIONS", "1000")
            ),
            operation_timeout=float(os.getenv("OPERATION_TIMEOUT", "5.0")),
        )

        # Monitoring settings
        monitoring = MonitoringConfig(
            enable_metrics=os.getenv("ENABLE_METRICS", "true").lower() == "true",
            enable_health_checks=os.getenv("ENABLE_HEALTH_CHECKS", "true").lower()
            == "true",
            metrics_buffer_size=int(os.getenv("METRICS_BUFFER_SIZE", "1000")),
            health_check_interval=float(os.getenv("HEALTH_CHECK_INTERVAL", "30.0")),
            health_check_timeout=float(os.getenv("HEALTH_CHECK_TIMEOUT", "5.0")),
            enable_openmetrics_export=os.getenv(
                "ENABLE_OPENMETRICS_EXPORT", "true"
            ).lower()
            == "true",
            enable_prometheus_integration=os.getenv(
                "ENABLE_PROMETHEUS_INTEGRATION", "true"
            ).lower()
            == "true",
        )

        # Circuit breaker settings
        circuit_breaker = CircuitBreakerConfig(
            enabled=os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true",
            failure_threshold=int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
            recovery_timeout=float(
                os.getenv("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", "60.0")
            ),
            half_open_max_calls=int(
                os.getenv("CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS", "3")
            ),
            failure_rate_threshold=float(
                os.getenv("CIRCUIT_BREAKER_FAILURE_RATE_THRESHOLD", "50.0")
            ),
            slow_call_duration_threshold=float(
                os.getenv("CIRCUIT_BREAKER_SLOW_CALL_DURATION_THRESHOLD", "2.0")
            ),
            slow_call_rate_threshold=float(
                os.getenv("CIRCUIT_BREAKER_SLOW_CALL_RATE_THRESHOLD", "50.0")
            ),
        )

        # Graceful degradation settings
        graceful_degradation = GracefulDegradationConfig(
            enabled=os.getenv("GRACEFUL_DEGRADATION_ENABLED", "true").lower() == "true",
            max_degradation_levels=int(
                os.getenv("GRACEFUL_DEGRADATION_MAX_LEVELS", "5")
            ),
            degradation_factor=float(os.getenv("GRACEFUL_DEGRADATION_FACTOR", "0.2")),
            recovery_factor=float(
                os.getenv("GRACEFUL_DEGRADATION_RECOVERY_FACTOR", "0.1")
            ),
            degradation_cooldown=float(
                os.getenv("GRACEFUL_DEGRADATION_COOLDOWN", "300.0")
            ),
            auto_recovery=os.getenv(
                "GRACEFUL_DEGRADATION_AUTO_RECOVERY", "true"
            ).lower()
            == "true",
        )

        # Logging settings
        logging = LoggingConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format=os.getenv(
                "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ),
            enable_structured_logging=os.getenv(
                "ENABLE_STRUCTURED_LOGGING", "true"
            ).lower()
            == "true",
            enable_json_logging=os.getenv("ENABLE_JSON_LOGGING", "false").lower()
            == "true",
            log_file=os.getenv("LOG_FILE"),
            max_log_size=int(os.getenv("MAX_LOG_SIZE", str(10 * 1024 * 1024))),
            backup_count=int(os.getenv("LOG_BACKUP_COUNT", "5")),
        )

        # Security settings
        security = SecurityConfig(
            enable_rate_limiting=os.getenv("ENABLE_RATE_LIMITING", "true").lower()
            == "true",
            max_requests_per_second=float(
                os.getenv("MAX_REQUESTS_PER_SECOND", "100.0")
            ),
            enable_allowlist=os.getenv("ENABLE_ALLOWLIST", "true").lower() == "true",
            enable_blocklist=os.getenv("ENABLE_BLOCKLIST", "true").lower() == "true",
            max_peer_connections=int(os.getenv("MAX_PEER_CONNECTIONS", "10")),
            connection_rate_limit=float(os.getenv("CONNECTION_RATE_LIMIT", "10.0")),
        )

        # Global settings
        environment = os.getenv("ENVIRONMENT", "production")
        debug = os.getenv("DEBUG", "false").lower() == "true"
        profile = os.getenv("PROFILE", "false").lower() == "true"
        version = os.getenv("VERSION", "1.0.0")

        # Deployment settings
        deployment_id = os.getenv("DEPLOYMENT_ID")
        region = os.getenv("REGION")
        cluster = os.getenv("CLUSTER")
        node_id = os.getenv("NODE_ID")

        return cls(
            connections=connections,
            memory=memory,
            performance=performance,
            monitoring=monitoring,
            circuit_breaker=circuit_breaker,
            graceful_degradation=graceful_degradation,
            logging=logging,
            security=security,
            environment=environment,
            debug=debug,
            profile=profile,
            version=version,
            deployment_id=deployment_id,
            region=region,
            cluster=cluster,
            node_id=node_id,
        )

    @classmethod
    def from_file(cls, config_path: str) -> ProductionConfig:
        """
        Load configuration from JSON file.

        Args:
            config_path: Path to configuration file

        Returns:
            ProductionConfig: Configuration loaded from file

        """
        with open(config_path) as f:
            config_data = json.load(f)

        # Create configuration objects from data
        connections = ConnectionConfig(**config_data.get("connections", {}))
        memory = MemoryConfig(**config_data.get("memory", {}))
        performance = PerformanceConfig(**config_data.get("performance", {}))
        monitoring = MonitoringConfig(**config_data.get("monitoring", {}))
        circuit_breaker = CircuitBreakerConfig(**config_data.get("circuit_breaker", {}))
        graceful_degradation = GracefulDegradationConfig(
            **config_data.get("graceful_degradation", {})
        )
        logging = LoggingConfig(**config_data.get("logging", {}))
        security = SecurityConfig(**config_data.get("security", {}))

        return cls(
            connections=connections,
            memory=memory,
            performance=performance,
            monitoring=monitoring,
            circuit_breaker=circuit_breaker,
            graceful_degradation=graceful_degradation,
            logging=logging,
            security=security,
            environment=config_data.get("environment", "production"),
            debug=config_data.get("debug", False),
            profile=config_data.get("profile", False),
            version=config_data.get("version", "1.0.0"),
            deployment_id=config_data.get("deployment_id"),
            region=config_data.get("region"),
            cluster=config_data.get("cluster"),
            node_id=config_data.get("node_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert configuration to dictionary.

        Returns:
            Dict containing configuration data

        """
        return {
            "connections": {
                "max_connections": self.connections.max_connections,
                "max_connections_per_peer": self.connections.max_connections_per_peer,
                "connection_timeout": self.connections.connection_timeout,
                "connection_keepalive": self.connections.connection_keepalive,
                "connection_retry_attempts": self.connections.connection_retry_attempts,
                "connection_retry_delay": self.connections.connection_retry_delay,
            },
            "memory": {
                "max_memory_mb": self.memory.max_memory_mb,
                "memory_pool_size": self.memory.memory_pool_size,
                "memory_pool_block_size": self.memory.memory_pool_block_size,
                "memory_cleanup_interval": self.memory.memory_cleanup_interval,
                "memory_monitoring_interval": self.memory.memory_monitoring_interval,
            },
            "performance": {
                "enable_connection_pooling": self.performance.enable_connection_pooling,
                "enable_memory_pooling": self.performance.enable_memory_pooling,
                "enable_lockfree_structures": (
                    self.performance.enable_lockfree_structures
                ),
                "enable_preallocation": self.performance.enable_preallocation,
                "max_concurrent_operations": self.performance.max_concurrent_operations,
                "operation_timeout": self.performance.operation_timeout,
            },
            "monitoring": {
                "enable_metrics": self.monitoring.enable_metrics,
                "enable_health_checks": self.monitoring.enable_health_checks,
                "metrics_buffer_size": self.monitoring.metrics_buffer_size,
                "health_check_interval": self.monitoring.health_check_interval,
                "health_check_timeout": self.monitoring.health_check_timeout,
                "alert_thresholds": self.monitoring.alert_thresholds,
                "enable_openmetrics_export": self.monitoring.enable_openmetrics_export,
                "enable_prometheus_integration": (
                    self.monitoring.enable_prometheus_integration
                ),
            },
            "circuit_breaker": {
                "enabled": self.circuit_breaker.enabled,
                "failure_threshold": self.circuit_breaker.failure_threshold,
                "recovery_timeout": self.circuit_breaker.recovery_timeout,
                "half_open_max_calls": self.circuit_breaker.half_open_max_calls,
                "failure_rate_threshold": self.circuit_breaker.failure_rate_threshold,
                "slow_call_duration_threshold": (
                    self.circuit_breaker.slow_call_duration_threshold
                ),
                "slow_call_rate_threshold": (
                    self.circuit_breaker.slow_call_rate_threshold
                ),
            },
            "graceful_degradation": {
                "enabled": self.graceful_degradation.enabled,
                "max_degradation_levels": (
                    self.graceful_degradation.max_degradation_levels
                ),
                "degradation_factor": self.graceful_degradation.degradation_factor,
                "recovery_factor": self.graceful_degradation.recovery_factor,
                "degradation_cooldown": self.graceful_degradation.degradation_cooldown,
                "auto_recovery": self.graceful_degradation.auto_recovery,
            },
            "logging": {
                "level": self.logging.level,
                "format": self.logging.format,
                "enable_structured_logging": self.logging.enable_structured_logging,
                "enable_json_logging": self.logging.enable_json_logging,
                "log_file": self.logging.log_file,
                "max_log_size": self.logging.max_log_size,
                "backup_count": self.logging.backup_count,
            },
            "security": {
                "enable_rate_limiting": self.security.enable_rate_limiting,
                "max_requests_per_second": self.security.max_requests_per_second,
                "enable_allowlist": self.security.enable_allowlist,
                "enable_blocklist": self.security.enable_blocklist,
                "max_peer_connections": self.security.max_peer_connections,
                "connection_rate_limit": self.security.connection_rate_limit,
            },
            "environment": self.environment,
            "debug": self.debug,
            "profile": self.profile,
            "version": self.version,
            "deployment_id": self.deployment_id,
            "region": self.region,
            "cluster": self.cluster,
            "node_id": self.node_id,
        }

    def to_file(self, config_path: str) -> None:
        """
        Save configuration to JSON file.

        Args:
            config_path: Path to save configuration file

        """
        with open(config_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def validate(self) -> list[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)

        """
        errors = []

        # Validate connection settings
        if self.connections.max_connections <= 0:
            errors.append("max_connections must be positive")
        if self.connections.max_connections_per_peer <= 0:
            errors.append("max_connections_per_peer must be positive")
        if self.connections.connection_timeout <= 0:
            errors.append("connection_timeout must be positive")

        # Validate memory settings
        if self.memory.max_memory_mb <= 0:
            errors.append("max_memory_mb must be positive")
        if self.memory.memory_pool_size <= 0:
            errors.append("memory_pool_size must be positive")
        if self.memory.memory_pool_block_size <= 0:
            errors.append("memory_pool_block_size must be positive")

        # Validate performance settings
        if self.performance.max_concurrent_operations <= 0:
            errors.append("max_concurrent_operations must be positive")
        if self.performance.operation_timeout <= 0:
            errors.append("operation_timeout must be positive")

        # Validate monitoring settings
        if self.monitoring.metrics_buffer_size <= 0:
            errors.append("metrics_buffer_size must be positive")
        if self.monitoring.health_check_interval <= 0:
            errors.append("health_check_interval must be positive")
        if self.monitoring.health_check_timeout <= 0:
            errors.append("health_check_timeout must be positive")

        # Validate circuit breaker settings
        if self.circuit_breaker.failure_threshold <= 0:
            errors.append("circuit_breaker.failure_threshold must be positive")
        if self.circuit_breaker.recovery_timeout <= 0:
            errors.append("circuit_breaker.recovery_timeout must be positive")

        # Validate graceful degradation settings
        if self.graceful_degradation.max_degradation_levels <= 0:
            errors.append(
                "graceful_degradation.max_degradation_levels must be positive"
            )
        if not 0 < self.graceful_degradation.degradation_factor < 1:
            errors.append(
                "graceful_degradation.degradation_factor must be between 0 and 1"
            )

        return errors

    def get_summary(self) -> dict[str, Any]:
        """
        Get configuration summary.

        Returns:
            Dict containing configuration summary

        """
        return {
            "environment": self.environment,
            "version": self.version,
            "deployment_id": self.deployment_id,
            "region": self.region,
            "cluster": self.cluster,
            "node_id": self.node_id,
            "debug": self.debug,
            "profile": self.profile,
            "connections": {
                "max_connections": self.connections.max_connections,
                "max_connections_per_peer": self.connections.max_connections_per_peer,
            },
            "memory": {
                "max_memory_mb": self.memory.max_memory_mb,
                "memory_pool_size": self.memory.memory_pool_size,
            },
            "performance": {
                "connection_pooling": self.performance.enable_connection_pooling,
                "memory_pooling": self.performance.enable_memory_pooling,
                "lockfree_structures": self.performance.enable_lockfree_structures,
            },
            "monitoring": {
                "metrics": self.monitoring.enable_metrics,
                "health_checks": self.monitoring.enable_health_checks,
                "openmetrics": self.monitoring.enable_openmetrics_export,
            },
            "circuit_breaker": {
                "enabled": self.circuit_breaker.enabled,
                "failure_threshold": self.circuit_breaker.failure_threshold,
            },
            "graceful_degradation": {
                "enabled": self.graceful_degradation.enabled,
                "max_levels": self.graceful_degradation.max_degradation_levels,
            },
        }

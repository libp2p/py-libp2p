"""
Enhanced error types for resource management.

This module implements comprehensive error types and error context building
for production-ready resource management, providing detailed error information
and context for debugging and monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any

import multiaddr

from libp2p.peer.id import ID


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for classification."""

    # Resource limit errors
    CONNECTION_LIMIT = "connection_limit"
    MEMORY_LIMIT = "memory_limit"
    STREAM_LIMIT = "stream_limit"
    PEER_LIMIT = "peer_limit"
    PROTOCOL_LIMIT = "protocol_limit"

    # System errors
    SYSTEM_ERROR = "system_error"
    NETWORK_ERROR = "network_error"
    TRANSPORT_ERROR = "transport_error"
    PROTOCOL_ERROR = "protocol_error"

    # Configuration errors
    CONFIG_ERROR = "config_error"
    VALIDATION_ERROR = "validation_error"

    # Operational errors
    OPERATIONAL_ERROR = "operational_error"
    MONITORING_ERROR = "monitoring_error"
    LIFECYCLE_ERROR = "lifecycle_error"


class ErrorCode(Enum):
    """Standardized error codes."""

    # Connection limit errors (1000-1099)
    CONNECTION_LIMIT_EXCEEDED = "CONN_001"
    CONNECTION_PENDING_LIMIT_EXCEEDED = "CONN_002"
    CONNECTION_ESTABLISHED_LIMIT_EXCEEDED = "CONN_003"
    CONNECTION_PER_PEER_LIMIT_EXCEEDED = "CONN_004"
    CONNECTION_TOTAL_LIMIT_EXCEEDED = "CONN_005"

    # Memory limit errors (1100-1199)
    MEMORY_LIMIT_EXCEEDED = "MEM_001"
    MEMORY_PROCESS_LIMIT_EXCEEDED = "MEM_002"
    MEMORY_SYSTEM_LIMIT_EXCEEDED = "MEM_003"
    MEMORY_MONITORING_FAILED = "MEM_004"

    # Stream limit errors (1200-1299)
    STREAM_LIMIT_EXCEEDED = "STR_001"
    STREAM_PER_CONNECTION_LIMIT_EXCEEDED = "STR_002"
    STREAM_PER_PEER_LIMIT_EXCEEDED = "STR_003"
    STREAM_TOTAL_LIMIT_EXCEEDED = "STR_004"

    # Peer limit errors (1300-1399)
    PEER_LIMIT_EXCEEDED = "PEER_001"
    PEER_CONNECTION_LIMIT_EXCEEDED = "PEER_002"
    PEER_STREAM_LIMIT_EXCEEDED = "PEER_003"

    # Protocol limit errors (1400-1499)
    PROTOCOL_LIMIT_EXCEEDED = "PROT_001"
    PROTOCOL_STREAM_LIMIT_EXCEEDED = "PROT_002"
    PROTOCOL_RATE_LIMIT_EXCEEDED = "PROT_003"

    # System errors (2000-2099)
    SYSTEM_ERROR = "SYS_001"
    SYSTEM_MONITORING_FAILED = "SYS_002"
    SYSTEM_RESOURCE_UNAVAILABLE = "SYS_003"

    # Network errors (2100-2199)
    NETWORK_ERROR = "NET_001"
    NETWORK_CONNECTION_FAILED = "NET_002"
    NETWORK_TIMEOUT = "NET_003"
    NETWORK_UNREACHABLE = "NET_004"

    # Transport errors (2200-2299)
    TRANSPORT_ERROR = "TRANS_001"
    TRANSPORT_CONNECTION_FAILED = "TRANS_002"
    TRANSPORT_STREAM_FAILED = "TRANS_003"
    TRANSPORT_PROTOCOL_ERROR = "TRANS_004"

    # Configuration errors (3000-3099)
    CONFIG_ERROR = "CFG_001"
    CONFIG_VALIDATION_FAILED = "CFG_002"
    CONFIG_INVALID_LIMITS = "CFG_003"
    CONFIG_MISSING_REQUIRED = "CFG_004"

    # Operational errors (4000-4099)
    OPERATIONAL_ERROR = "OP_001"
    OPERATIONAL_MONITORING_FAILED = "OP_002"
    OPERATIONAL_LIFECYCLE_FAILED = "OP_003"
    OPERATIONAL_EVENT_FAILED = "OP_004"


@dataclass
class ErrorContext:
    """Context information for errors."""

    # Basic error information
    error_code: ErrorCode
    error_category: ErrorCategory
    severity: ErrorSeverity
    message: str
    timestamp: float = field(default_factory=time.time)

    # Resource information
    resource_type: str | None = None
    resource_id: str | None = None
    resource_scope: str | None = None

    # Connection information
    connection_id: str | None = None
    peer_id: ID | None = None
    local_addr: multiaddr.Multiaddr | None = None
    remote_addr: multiaddr.Multiaddr | None = None

    # Limit information
    limit_type: str | None = None
    limit_value: int | float | None = None
    current_value: int | float | None = None
    limit_percentage: float | None = None

    # System information
    system_memory_total: int | None = None
    system_memory_available: int | None = None
    system_memory_percent: float | None = None
    process_memory_bytes: int | None = None
    process_memory_percent: float | None = None

    # Additional context
    metadata: dict[str, Any] = field(default_factory=dict)
    stack_trace: str | None = None
    previous_errors: list[ErrorContext] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert error context to dictionary."""
        return {
            "error_code": self.error_code.value,
            "error_category": self.error_category.value,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_scope": self.resource_scope,
            "connection_id": self.connection_id,
            "peer_id": str(self.peer_id) if self.peer_id else None,
            "local_addr": str(self.local_addr) if self.local_addr else None,
            "remote_addr": str(self.remote_addr) if self.remote_addr else None,
            "limit_type": self.limit_type,
            "limit_value": self.limit_value,
            "current_value": self.current_value,
            "limit_percentage": self.limit_percentage,
            "system_memory_total": self.system_memory_total,
            "system_memory_available": self.system_memory_available,
            "system_memory_percent": self.system_memory_percent,
            "process_memory_bytes": self.process_memory_bytes,
            "process_memory_percent": self.process_memory_percent,
            "metadata": self.metadata,
            "stack_trace": self.stack_trace,
            "previous_errors": [err.to_dict() for err in self.previous_errors],
        }

    def __str__(self) -> str:
        """String representation of error context."""
        return (
            f"{self.error_code.value}: {self.message} "
            f"(severity={self.severity.value}, category={self.error_category.value})"
        )


class ResourceLimitExceededError(Exception):
    """Enhanced exception for resource limit exceeded errors."""

    def __init__(
        self,
        error_context: ErrorContext,
        original_exception: Exception | None = None,
    ):
        """
        Initialize resource limit exceeded error.

        Args:
            error_context: Detailed error context
            original_exception: Original exception that caused this error

        """
        self.error_context = error_context
        self.original_exception = original_exception

        # Build error message
        message = self._build_error_message()
        super().__init__(message)

    def _build_error_message(self) -> str:
        """Build detailed error message."""
        ctx = self.error_context

        # Base message
        message = f"{ctx.error_code.value}: {ctx.message}"

        # Add limit information
        if ctx.limit_type and ctx.limit_value is not None:
            if ctx.current_value is not None:
                message += f" (limit={ctx.limit_value}, current={ctx.current_value})"
            else:
                message += f" (limit={ctx.limit_value})"

        # Add resource information
        if ctx.resource_type:
            message += f" [resource={ctx.resource_type}"
            if ctx.resource_id:
                message += f":{ctx.resource_id}"
            message += "]"

        # Add connection information
        if ctx.connection_id:
            message += f" [connection={ctx.connection_id}]"

        # Add peer information
        if ctx.peer_id:
            message += f" [peer={ctx.peer_id}]"

        return message

    def get_error_summary(self) -> dict[str, Any]:
        """Get error summary for monitoring."""
        return {
            "error_code": self.error_context.error_code.value,
            "error_category": self.error_context.error_category.value,
            "severity": self.error_context.severity.value,
            "message": self.error_context.message,
            "timestamp": self.error_context.timestamp,
            "resource_type": self.error_context.resource_type,
            "limit_type": self.error_context.limit_type,
            "limit_value": self.error_context.limit_value,
            "current_value": self.error_context.current_value,
            "has_original_exception": self.original_exception is not None,
        }

    def __str__(self) -> str:
        """String representation of the error."""
        return self._build_error_message()


class SystemResourceError(Exception):
    """Enhanced exception for system resource errors."""

    def __init__(
        self,
        error_context: ErrorContext,
        original_exception: Exception | None = None,
    ):
        """
        Initialize system resource error.

        Args:
            error_context: Detailed error context
            original_exception: Original exception that caused this error

        """
        self.error_context = error_context
        self.original_exception = original_exception

        # Build error message
        message = self._build_error_message()
        super().__init__(message)

    def _build_error_message(self) -> str:
        """Build detailed error message."""
        ctx = self.error_context

        # Base message
        message = f"{ctx.error_code.value}: {ctx.message}"

        # Add system information
        if ctx.system_memory_total is not None:
            message += f" [system_memory={ctx.system_memory_total} bytes"
            if ctx.system_memory_percent is not None:
                message += f" ({ctx.system_memory_percent:.1f}%)"
            message += "]"

        # Add process information
        if ctx.process_memory_bytes is not None:
            message += f" [process_memory={ctx.process_memory_bytes} bytes"
            if ctx.process_memory_percent is not None:
                message += f" ({ctx.process_memory_percent:.1f}%)"
            message += "]"

        return message

    def get_error_summary(self) -> dict[str, Any]:
        """Get error summary for monitoring."""
        return {
            "error_code": self.error_context.error_code.value,
            "error_category": self.error_context.error_category.value,
            "severity": self.error_context.severity.value,
            "message": self.error_context.message,
            "timestamp": self.error_context.timestamp,
            "system_memory_total": self.error_context.system_memory_total,
            "system_memory_percent": self.error_context.system_memory_percent,
            "process_memory_bytes": self.error_context.process_memory_bytes,
            "process_memory_percent": self.error_context.process_memory_percent,
            "has_original_exception": self.original_exception is not None,
        }

    def __str__(self) -> str:
        """String representation of the error."""
        return self._build_error_message()


class ConfigurationError(Exception):
    """Enhanced exception for configuration errors."""

    def __init__(
        self,
        error_context: ErrorContext,
        original_exception: Exception | None = None,
    ):
        """
        Initialize configuration error.

        Args:
            error_context: Detailed error context
            original_exception: Original exception that caused this error

        """
        self.error_context = error_context
        self.original_exception = original_exception

        # Build error message
        message = self._build_error_message()
        super().__init__(message)

    def _build_error_message(self) -> str:
        """Build detailed error message."""
        ctx = self.error_context

        # Base message
        message = f"{ctx.error_code.value}: {ctx.message}"

        # Add configuration information
        if ctx.metadata.get("config_key"):
            message += f" [config_key={ctx.metadata['config_key']}]"

        if ctx.metadata.get("config_value"):
            message += f" [config_value={ctx.metadata['config_value']}]"

        return message

    def get_error_summary(self) -> dict[str, Any]:
        """Get error summary for monitoring."""
        return {
            "error_code": self.error_context.error_code.value,
            "error_category": self.error_context.error_category.value,
            "severity": self.error_context.severity.value,
            "message": self.error_context.message,
            "timestamp": self.error_context.timestamp,
            "config_key": self.error_context.metadata.get("config_key"),
            "config_value": self.error_context.metadata.get("config_value"),
            "has_original_exception": self.original_exception is not None,
        }

    def __str__(self) -> str:
        """String representation of the error."""
        return self._build_error_message()


class OperationalError(Exception):
    """Enhanced exception for operational errors."""

    def __init__(
        self,
        error_context: ErrorContext,
        original_exception: Exception | None = None,
    ):
        """
        Initialize operational error.

        Args:
            error_context: Detailed error context
            original_exception: Original exception that caused this error

        """
        self.error_context = error_context
        self.original_exception = original_exception

        # Build error message
        message = self._build_error_message()
        super().__init__(message)

    def _build_error_message(self) -> str:
        """Build detailed error message."""
        ctx = self.error_context

        # Base message
        message = f"{ctx.error_code.value}: {ctx.message}"

        # Add operational information
        if ctx.metadata.get("operation"):
            message += f" [operation={ctx.metadata['operation']}]"

        if ctx.metadata.get("component"):
            message += f" [component={ctx.metadata['component']}]"

        return message

    def get_error_summary(self) -> dict[str, Any]:
        """Get error summary for monitoring."""
        return {
            "error_code": self.error_context.error_code.value,
            "error_category": self.error_context.error_category.value,
            "severity": self.error_context.severity.value,
            "message": self.error_context.message,
            "timestamp": self.error_context.timestamp,
            "operation": self.error_context.metadata.get("operation"),
            "component": self.error_context.metadata.get("component"),
            "has_original_exception": self.original_exception is not None,
        }

    def __str__(self) -> str:
        """String representation of the error."""
        return self._build_error_message()


# Error factory functions
def create_connection_limit_error(
    limit_type: str,
    limit_value: int | float,
    current_value: int | float,
    connection_id: str | None = None,
    peer_id: ID | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResourceLimitExceededError:
    """Create a connection limit exceeded error."""
    error_code = ErrorCode.CONNECTION_LIMIT_EXCEEDED
    if limit_type == "pending":
        error_code = ErrorCode.CONNECTION_PENDING_LIMIT_EXCEEDED
    elif limit_type == "established":
        error_code = ErrorCode.CONNECTION_ESTABLISHED_LIMIT_EXCEEDED
    elif limit_type == "per_peer":
        error_code = ErrorCode.CONNECTION_PER_PEER_LIMIT_EXCEEDED
    elif limit_type == "total":
        error_code = ErrorCode.CONNECTION_TOTAL_LIMIT_EXCEEDED

    context = ErrorContext(
        error_code=error_code,
        error_category=ErrorCategory.CONNECTION_LIMIT,
        severity=ErrorSeverity.HIGH,
        message=message or f"Connection {limit_type} limit exceeded",
        resource_type="connection",
        connection_id=connection_id,
        peer_id=peer_id,
        limit_type=limit_type,
        limit_value=limit_value,
        current_value=current_value,
        limit_percentage=(
            (current_value / limit_value * 100) if limit_value > 0 else None
        ),
        metadata=metadata or {},
    )

    return ResourceLimitExceededError(context)


def create_memory_limit_error(
    limit_type: str,
    limit_value: int | float,
    current_value: int | float,
    system_memory_total: int | None = None,
    system_memory_available: int | None = None,
    process_memory_bytes: int | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SystemResourceError:
    """Create a memory limit exceeded error."""
    error_code = ErrorCode.MEMORY_LIMIT_EXCEEDED
    if limit_type == "process":
        error_code = ErrorCode.MEMORY_PROCESS_LIMIT_EXCEEDED
    elif limit_type == "system":
        error_code = ErrorCode.MEMORY_SYSTEM_LIMIT_EXCEEDED

    context = ErrorContext(
        error_code=error_code,
        error_category=ErrorCategory.MEMORY_LIMIT,
        severity=ErrorSeverity.CRITICAL,
        message=message or f"Memory {limit_type} limit exceeded",
        resource_type="memory",
        limit_type=limit_type,
        limit_value=limit_value,
        current_value=current_value,
        limit_percentage=(
            (current_value / limit_value * 100) if limit_value > 0 else None
        ),
        system_memory_total=system_memory_total,
        system_memory_available=system_memory_available,
        system_memory_percent=(
            (100 - (system_memory_available / system_memory_total * 100))
            if system_memory_total and system_memory_available
            else None
        ),
        process_memory_bytes=process_memory_bytes,
        process_memory_percent=(
            (process_memory_bytes / system_memory_total * 100)
            if process_memory_bytes and system_memory_total
            else None
        ),
        metadata=metadata or {},
    )

    return SystemResourceError(context)


def create_configuration_error(
    config_key: str,
    config_value: Any,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ConfigurationError:
    """Create a configuration error."""
    context = ErrorContext(
        error_code=ErrorCode.CONFIG_ERROR,
        error_category=ErrorCategory.CONFIG_ERROR,
        severity=ErrorSeverity.MEDIUM,
        message=message or f"Configuration error for {config_key}",
        metadata={
            **(metadata or {}),
            "config_key": config_key,
            "config_value": str(config_value),
        },
    )

    return ConfigurationError(context)


def create_operational_error(
    operation: str,
    component: str,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OperationalError:
    """Create an operational error."""
    context = ErrorContext(
        error_code=ErrorCode.OPERATIONAL_ERROR,
        error_category=ErrorCategory.OPERATIONAL_ERROR,
        severity=ErrorSeverity.MEDIUM,
        message=message or f"Operational error in {component} during {operation}",
        metadata={
            **(metadata or {}),
            "operation": operation,
            "component": component,
        },
    )

    return OperationalError(context)

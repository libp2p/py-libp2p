"""
Error context builder for resource management.

This module implements error context building utilities that provide
comprehensive error information and context for debugging and monitoring.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional, Union

import multiaddr

from libp2p.peer.id import ID

from .enhanced_errors import (
    ConfigurationError,
    ErrorCategory,
    ErrorCode,
    ErrorContext,
    ErrorSeverity,
    OperationalError,
    ResourceLimitExceededError,
    SystemResourceError,
)


class ErrorContextBuilder:
    """
    Builder for error context information.

    This class provides a fluent interface for building comprehensive
    error context information for resource management errors.
    """

    def __init__(self) -> None:
        """Initialize error context builder."""
        self._context = ErrorContext(
            error_code=ErrorCode.SYSTEM_ERROR,
            error_category=ErrorCategory.SYSTEM_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="",
        )
        self._original_exception: Optional[Exception] = None

    def with_error_code(self, error_code: ErrorCode) -> ErrorContextBuilder:
        """
        Set the error code.

        Args:
            error_code: Error code to set

        Returns:
            Self for method chaining

        """
        self._context.error_code = error_code
        return self

    def with_error_category(self, category: ErrorCategory) -> ErrorContextBuilder:
        """
        Set the error category.

        Args:
            category: Error category to set

        Returns:
            Self for method chaining

        """
        self._context.error_category = category
        return self

    def with_severity(self, severity: ErrorSeverity) -> ErrorContextBuilder:
        """
        Set the error severity.

        Args:
            severity: Error severity to set

        Returns:
            Self for method chaining

        """
        self._context.severity = severity
        return self

    def with_message(self, message: str) -> ErrorContextBuilder:
        """
        Set the error message.

        Args:
            message: Error message to set

        Returns:
            Self for method chaining

        """
        self._context.message = message
        return self

    def with_resource_info(
        self,
        resource_type: str,
        resource_id: Optional[str] = None,
        resource_scope: Optional[str] = None,
    ) -> ErrorContextBuilder:
        """
        Set resource information.

        Args:
            resource_type: Type of resource
            resource_id: Resource identifier
            resource_scope: Resource scope

        Returns:
            Self for method chaining

        """
        self._context.resource_type = resource_type
        self._context.resource_id = resource_id
        self._context.resource_scope = resource_scope
        return self

    def with_connection_info(
        self,
        connection_id: Optional[str] = None,
        peer_id: Optional[ID] = None,
        local_addr: Optional[multiaddr.Multiaddr] = None,
        remote_addr: Optional[multiaddr.Multiaddr] = None,
    ) -> ErrorContextBuilder:
        """
        Set connection information.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID
            local_addr: Local address
            remote_addr: Remote address

        Returns:
            Self for method chaining

        """
        self._context.connection_id = connection_id
        self._context.peer_id = peer_id
        self._context.local_addr = local_addr
        self._context.remote_addr = remote_addr
        return self

    def with_limit_info(
        self,
        limit_type: str,
        limit_value: Union[int, float],
        current_value: Union[int, float],
    ) -> ErrorContextBuilder:
        """
        Set limit information.

        Args:
            limit_type: Type of limit
            limit_value: Limit value
            current_value: Current value

        Returns:
            Self for method chaining

        """
        self._context.limit_type = limit_type
        self._context.limit_value = limit_value
        self._context.current_value = current_value
        self._context.limit_percentage = (
            (current_value / limit_value * 100) if limit_value > 0 else None
        )
        return self

    def with_system_info(
        self,
        system_memory_total: Optional[int] = None,
        system_memory_available: Optional[int] = None,
        system_memory_percent: Optional[float] = None,
        process_memory_bytes: Optional[int] = None,
        process_memory_percent: Optional[float] = None,
    ) -> ErrorContextBuilder:
        """
        Set system information.

        Args:
            system_memory_total: Total system memory
            system_memory_available: Available system memory
            system_memory_percent: System memory usage percentage
            process_memory_bytes: Process memory usage
            process_memory_percent: Process memory usage percentage

        Returns:
            Self for method chaining

        """
        self._context.system_memory_total = system_memory_total
        self._context.system_memory_available = system_memory_available
        self._context.system_memory_percent = system_memory_percent
        self._context.process_memory_bytes = process_memory_bytes
        self._context.process_memory_percent = process_memory_percent
        return self

    def with_metadata(self, metadata: Dict[str, Any]) -> ErrorContextBuilder:
        """
        Set metadata.

        Args:
            metadata: Metadata dictionary

        Returns:
            Self for method chaining

        """
        self._context.metadata.update(metadata)
        return self

    def with_stack_trace(
        self, stack_trace: Optional[str] = None
    ) -> ErrorContextBuilder:
        """
        Set stack trace.

        Args:
            stack_trace: Stack trace string, or None to capture current trace

        Returns:
            Self for method chaining

        """
        if stack_trace is None:
            stack_trace = traceback.format_exc()
        self._context.stack_trace = stack_trace
        return self

    def with_original_exception(self, exception: Exception) -> ErrorContextBuilder:
        """
        Set original exception.

        Args:
            exception: Original exception that caused this error

        Returns:
            Self for method chaining

        """
        self._original_exception = exception
        return self

    def with_previous_errors(self, errors: List[ErrorContext]) -> ErrorContextBuilder:
        """
        Set previous errors.

        Args:
            errors: List of previous error contexts

        Returns:
            Self for method chaining

        """
        self._context.previous_errors = errors
        return self

    def build_resource_limit_error(self) -> ResourceLimitExceededError:
        """
        Build a resource limit exceeded error.

        Returns:
            ResourceLimitExceededError: Built error

        """
        return ResourceLimitExceededError(self._context, self._original_exception)

    def build_system_resource_error(self) -> SystemResourceError:
        """
        Build a system resource error.

        Returns:
            SystemResourceError: Built error

        """
        return SystemResourceError(self._context, self._original_exception)

    def build_configuration_error(self) -> ConfigurationError:
        """
        Build a configuration error.

        Returns:
            ConfigurationError: Built error

        """
        return ConfigurationError(self._context, self._original_exception)

    def build_operational_error(self) -> OperationalError:
        """
        Build an operational error.

        Returns:
            OperationalError: Built error

        """
        return OperationalError(self._context, self._original_exception)

    def build_context(self) -> ErrorContext:
        """
        Build the error context.

        Returns:
            ErrorContext: Built error context

        """
        return self._context

    def reset(self) -> ErrorContextBuilder:
        """
        Reset the builder to initial state.

        Returns:
            Self for method chaining

        """
        self._context = ErrorContext(
            error_code=ErrorCode.SYSTEM_ERROR,
            error_category=ErrorCategory.SYSTEM_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="",
        )
        self._original_exception = None
        return self


class ErrorContextCollector:
    """
    Collector for error context information.

    This class provides utilities for collecting and managing
    error context information across the resource management system.
    """

    def __init__(self, max_errors: int = 1000):
        """
        Initialize error context collector.

        Args:
            max_errors: Maximum number of errors to keep

        """
        self.max_errors = max_errors
        self._errors: List[ErrorContext] = []
        self._error_counts: Dict[str, int] = {}
        self._severity_counts: Dict[ErrorSeverity, int] = {}
        self._category_counts: Dict[ErrorCategory, int] = {}

    def add_error(self, error_context: ErrorContext) -> None:
        """
        Add an error context to the collector.

        Args:
            error_context: Error context to add

        """
        # Add to errors list
        self._errors.append(error_context)

        # Trim if necessary
        if len(self._errors) > self.max_errors:
            self._errors.pop(0)

        # Update counts
        error_code = error_context.error_code.value
        self._error_counts[error_code] = self._error_counts.get(error_code, 0) + 1

        severity = error_context.severity
        self._severity_counts[severity] = self._severity_counts.get(severity, 0) + 1

        category = error_context.error_category
        self._category_counts[category] = self._category_counts.get(category, 0) + 1

    def get_errors(
        self,
        error_code: Optional[ErrorCode] = None,
        severity: Optional[ErrorSeverity] = None,
        category: Optional[ErrorCategory] = None,
        limit: Optional[int] = None,
    ) -> List[ErrorContext]:
        """
        Get errors matching the specified criteria.

        Args:
            error_code: Filter by error code
            severity: Filter by severity
            category: Filter by category
            limit: Maximum number of errors to return

        Returns:
            List of matching error contexts

        """
        errors = self._errors

        if error_code is not None:
            errors = [e for e in errors if e.error_code == error_code]

        if severity is not None:
            errors = [e for e in errors if e.severity == severity]

        if category is not None:
            errors = [e for e in errors if e.error_category == category]

        if limit is not None:
            errors = errors[-limit:]

        return errors

    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get error statistics.

        Returns:
            Dictionary of error statistics

        """
        return {
            "total_errors": len(self._errors),
            "error_counts": self._error_counts,
            "severity_counts": {s.value: c for s, c in self._severity_counts.items()},
            "category_counts": {
                c.value: c for c, count in self._category_counts.items()
            },
            "recent_errors": len([
                e for e in self._errors if time.time() - e.timestamp < 3600
            ]),  # Last hour
        }

    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get error summary for monitoring.

        Returns:
            Dictionary of error summary

        """
        if not self._errors:
            return {"total_errors": 0, "recent_errors": 0}

        recent_errors = [e for e in self._errors if time.time() - e.timestamp < 3600]

        # Get most common error codes
        error_code_counts: Dict[str, int] = {}
        for error in self._errors:
            code = error.error_code.value
            error_code_counts[code] = error_code_counts.get(code, 0) + 1

        most_common_errors = sorted(
            error_code_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # Get severity distribution
        severity_distribution = {}
        for severity, count in self._severity_counts.items():
            severity_distribution[severity.value] = count

        return {
            "total_errors": len(self._errors),
            "recent_errors": len(recent_errors),
            "most_common_errors": most_common_errors,
            "severity_distribution": severity_distribution,
            "category_distribution": {
                category.value: count
                for category, count in self._category_counts.items()
            },
        }

    def clear_errors(self) -> None:
        """Clear all collected errors."""
        self._errors.clear()
        self._error_counts.clear()
        self._severity_counts.clear()
        self._category_counts.clear()

    def __str__(self) -> str:
        """String representation of error collector."""
        stats = self.get_error_statistics()
        return (
            f"ErrorContextCollector("
            f"total_errors={stats['total_errors']}, "
            f"recent_errors={stats['recent_errors']})"
        )


# Convenience functions
def create_error_context_builder() -> ErrorContextBuilder:
    """
    Create a new error context builder.

    Returns:
        ErrorContextBuilder: New error context builder

    """
    return ErrorContextBuilder()


def create_error_collector(max_errors: int = 1000) -> ErrorContextCollector:
    """
    Create a new error context collector.

    Args:
        max_errors: Maximum number of errors to keep

    Returns:
        ErrorContextCollector: New error context collector

    """
    return ErrorContextCollector(max_errors)

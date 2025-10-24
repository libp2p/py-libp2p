"""
Resource manager exception classes.
"""

from __future__ import annotations


class ResourceManagerException(Exception):
    """Base exception for all resource manager errors."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ResourceLimitExceeded(ResourceManagerException):
    """Exception raised when a resource limit is exceeded."""

    def __init__(
        self,
        scope_name: str | None = None,
        resource_type: str | None = None,
        requested: int | None = None,
        available: int | None = None,
        message: str | None = None,
    ):
        self.scope_name = scope_name
        self.resource_type = resource_type
        self.requested = requested
        self.available = available

        if message:
            super().__init__(message)
        elif (
            scope_name is not None
            and requested is not None
            and resource_type is not None
            and available is not None
        ):
            msg = (
                f"Resource limit exceeded in scope '{scope_name}': "
                f"requested {requested} {resource_type}, available {available}"
            )
            super().__init__(msg)
        else:
            super().__init__("Resource limit exceeded")


class ScopeClosedException(ResourceManagerException):
    """Exception raised when trying to use a closed resource scope."""

    def __init__(
        self,
        scope_name: str | None = None,
        message: str | None = None,
    ):
        self.scope_name = scope_name

        if message:
            super().__init__(message)
        elif scope_name:
            super().__init__(f"Operation attempted on closed scope: {scope_name}")
        else:
            super().__init__("Operation attempted on closed scope")


class InvalidResourceManagerState(ResourceManagerException):
    """Exception raised when the resource manager is in an invalid state."""

    def __init__(self, message: str):
        super().__init__(message)


# Legacy exceptions for backward compatibility
class MemoryLimitExceeded(ResourceLimitExceeded):
    """Exception raised when memory limit is exceeded."""

    def __init__(self, current: int, attempted: int, limit: int, priority: int):
        self.current = current
        self.attempted = attempted
        self.limit = limit
        self.priority = priority
        super().__init__(
            message=f"Memory limit exceeded: current={current}, attempted={attempted}, "
            f"limit={limit}, priority={priority}"
        )


class StreamOrConnLimitExceeded(ResourceLimitExceeded):
    """Exception for stream or connection limit exceeded errors."""

    def __init__(self, current: int, attempted: int, limit: int, resource_type: str):
        self.current = current
        self.attempted = attempted
        self.limit = limit

        # Call parent with consistent resource_type
        super().__init__(
            scope_name="stream/conn",
            resource_type=resource_type,
            requested=attempted,
            available=limit - current,
            message=f"{resource_type} limit exceeded: current={current}, "
            f"attempted={attempted}, limit={limit}",
        )


class ResourceScopeClosed(ScopeClosedException):
    """Legacy alias for ScopeClosedException."""

    pass

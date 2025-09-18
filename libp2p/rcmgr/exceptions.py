"""
Resource manager exception classes.
"""


class ResourceLimitExceeded(Exception):
    """Base exception for resource limit exceeded."""

    pass


class MemoryLimitExceeded(ResourceLimitExceeded):
    """Exception raised when memory limit is exceeded."""

    def __init__(self, current: int, attempted: int, limit: int, priority: int):
        self.current = current
        self.attempted = attempted
        self.limit = limit
        self.priority = priority
        super().__init__(
            f"Memory limit exceeded: current={current}, attempted={attempted}, "
            f"limit={limit}, priority={priority}"
        )


class StreamOrConnLimitExceeded(ResourceLimitExceeded):
    """Exception raised when stream or connection limit is exceeded."""

    def __init__(self, current: int, attempted: int, limit: int, resource_type: str):
        self.current = current
        self.attempted = attempted
        self.limit = limit
        self.resource_type = resource_type
        super().__init__(
            f"{resource_type} limit exceeded: current={current}, "
            f"attempted={attempted}, limit={limit}"
        )


class ResourceScopeClosed(Exception):
    """Exception raised when trying to use a closed resource scope."""

    pass

"""
Exceptions for the async_service implementation.
"""

class ServiceException(Exception):
    """Base class for Service exceptions"""
    pass

class LifecycleError(ServiceException):
    """Raised when an action would violate the service lifecycle rules."""
    pass

class DaemonTaskExit(ServiceException):
    """Raised when a daemon task exits."""
    pass
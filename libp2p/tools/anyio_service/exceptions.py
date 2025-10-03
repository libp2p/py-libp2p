"""Exceptions used by the AnyIO‐based service framework."""


class ServiceException(Exception):
    """Base class for Service exceptions"""


class LifecycleError(ServiceException):
    """
    Error raised when service operations are performed outside of service lifecycle.
    """


class DaemonTaskExit(ServiceException):
    """Exception raised when a daemon task exits unexpectedly"""


class TooManyChildrenException(ServiceException):
    """Raised when too many child tasks are spawned"""

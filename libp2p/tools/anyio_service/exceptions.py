class ServiceException(Exception):
    """
    Base class for Service exceptions
    """


class LifecycleError(ServiceException):
    """
    Raised when an action would violate the service lifecycle rules.
    """


class DaemonTaskExit(ServiceException):
    """
    Raised when a daemon task exits unexpectedly.
    """


class TooManyChildrenException(ServiceException):
    """
    Raised when a service adds too many children. It is a sign of task leakage
    that needs to be prevented.
    """

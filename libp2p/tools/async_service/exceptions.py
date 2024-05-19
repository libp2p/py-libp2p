# Copied from https://github.com/ethereum/async-service


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
    Raised when an action would violate the service lifecycle rules.
    """


class TooManyChildrenException(ServiceException):
    """
    Raised when a service adds too many children. It is a sign of task leakage
    that needs to be prevented.
    """

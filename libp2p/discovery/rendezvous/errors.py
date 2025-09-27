"""
Rendezvous protocol error handling.
"""

from .pb.rendezvous_pb2 import Message


class RendezvousError(Exception):
    """Base exception for rendezvous protocol errors."""

    def __init__(self, status: Message.ResponseStatus.ValueType, message: str = ""):
        self.status = status
        self.message = message
        super().__init__(f"Rendezvous error {status}: {message}")


class InvalidNamespaceError(RendezvousError):
    """Raised when namespace is invalid."""

    def __init__(self, message: str = "Invalid namespace"):
        super().__init__(Message.ResponseStatus.E_INVALID_NAMESPACE, message)


class InvalidPeerInfoError(RendezvousError):
    """Raised when peer information is invalid."""

    def __init__(self, message: str = "Invalid peer info"):
        super().__init__(Message.ResponseStatus.E_INVALID_PEER_INFO, message)


class InvalidTTLError(RendezvousError):
    """Raised when TTL is invalid."""

    def __init__(self, message: str = "Invalid TTL"):
        super().__init__(Message.ResponseStatus.E_INVALID_TTL, message)


class InvalidCookieError(RendezvousError):
    """Raised when discovery cookie is invalid."""

    def __init__(self, message: str = "Invalid cookie"):
        super().__init__(Message.ResponseStatus.E_INVALID_COOKIE, message)


class NotAuthorizedError(RendezvousError):
    """Raised when operation is not authorized."""

    def __init__(self, message: str = "Not authorized"):
        super().__init__(Message.ResponseStatus.E_NOT_AUTHORIZED, message)


class InternalError(RendezvousError):
    """Raised when server encounters internal error."""

    def __init__(self, message: str = "Internal server error"):
        super().__init__(Message.ResponseStatus.E_INTERNAL_ERROR, message)


class UnavailableError(RendezvousError):
    """Raised when service is unavailable."""

    def __init__(self, message: str = "Service unavailable"):
        super().__init__(Message.ResponseStatus.E_UNAVAILABLE, message)


def status_to_exception(
    status: Message.ResponseStatus.ValueType, message: str = ""
) -> RendezvousError | None:
    """Convert a protobuf status to the appropriate exception."""
    if status == Message.ResponseStatus.OK:
        return None
    elif status == Message.ResponseStatus.E_INVALID_NAMESPACE:
        return InvalidNamespaceError(message)
    elif status == Message.ResponseStatus.E_INVALID_PEER_INFO:
        return InvalidPeerInfoError(message)
    elif status == Message.ResponseStatus.E_INVALID_TTL:
        return InvalidTTLError(message)
    elif status == Message.ResponseStatus.E_INVALID_COOKIE:
        return InvalidCookieError(message)
    elif status == Message.ResponseStatus.E_NOT_AUTHORIZED:
        return NotAuthorizedError(message)
    elif status == Message.ResponseStatus.E_INTERNAL_ERROR:
        return InternalError(message)
    elif status == Message.ResponseStatus.E_UNAVAILABLE:
        return UnavailableError(message)
    else:
        return RendezvousError(status, message)

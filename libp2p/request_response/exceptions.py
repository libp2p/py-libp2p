from libp2p.exceptions import BaseLibp2pError


class RequestResponseError(BaseLibp2pError):
    """Base error for the request/response helper."""


class RequestTimeoutError(RequestResponseError):
    """Raised when a request/response exchange exceeds the configured timeout."""


class ProtocolNotSupportedError(RequestResponseError):
    """Raised when the remote peer supports none of the requested protocols."""


class RequestEncodeError(RequestResponseError):
    """Raised when request serialization fails."""


class RequestDecodeError(RequestResponseError):
    """Raised when request deserialization fails on the server side."""


class ResponseEncodeError(RequestResponseError):
    """Raised when response serialization fails on the server side."""


class ResponseDecodeError(RequestResponseError):
    """Raised when response deserialization fails on the client side."""


class MessageTooLargeError(RequestResponseError):
    """Raised when a framed request or response exceeds configured limits."""


class RequestTransportError(RequestResponseError):
    """Raised when transport- or stream-level failures interrupt a request."""

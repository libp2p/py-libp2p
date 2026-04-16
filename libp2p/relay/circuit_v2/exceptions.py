"""Circuit Relay v2 exceptions."""

from libp2p.exceptions import BaseLibp2pError

from .protocol_buffer import StatusCode


class RelayError(BaseLibp2pError):
    """Base exception for Circuit Relay errors."""

    pass


class RelayConnectionError(RelayError):
    """
    Raised when a relay connection fails.

    Carries the structured ``status_code`` so that callers can branch on
    the relay status (e.g. ``PERMISSION_DENIED``, ``RESOURCE_LIMIT_EXCEEDED``)
    without resorting to string matching on the error message.
    """

    def __init__(
        self,
        message: str,
        status_code: StatusCode | None = None,
        status_msg: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.status_msg = status_msg

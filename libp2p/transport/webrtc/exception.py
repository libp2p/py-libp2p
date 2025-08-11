"""
WebRTC Transport exceptions
"""


class WebRTCError(Exception):
    """Base exception for all WebRTC transport errors."""

    def __init__(self, message: str, error_code: int | None = None):
        super().__init__(message)
        self.error_code = error_code


# Transport-level exceptions


class WebRTCTransportError(WebRTCError):
    """Base exception for WebRTC transport operations."""

    pass


class WebRTCDialError(WebRTCTransportError):
    """Error occurred during WebRTC connection establishment."""

    pass


class WebRTCListenError(WebRTCTransportError):
    """Error occurred during WebRTC listener operations."""

    pass


class WebRTCSecurityError(WebRTCTransportError):
    """Error related to WebRTC security/TLS operations."""

    pass


class WebRTCHandshakeError(WebRTCError):
    """Error during WebRTC handshake process."""

    pass


class WebRTCPeerVerificationError(WebRTCHandshakeError):
    """Error verifying peer identity during handshake."""

    pass


# Stream-level exceptions


class WebRTCStreamError(WebRTCError):
    """Base exception for WebRTC stream operations."""

    def __init__(
        self,
        message: str,
        stream_id: str | None = None,
        error_code: int | None = None,
    ):
        super().__init__(message, error_code)
        self.stream_id = stream_id


class WebRTCStreamClosedError(WebRTCStreamError):
    """Stream is closed and cannot be used for I/O operations."""

    pass


class WebRTCStreamResetError(WebRTCStreamError):
    """Stream was reset by local or remote peer."""

    def __init__(
        self,
        message: str,
        stream_id: str | None = None,
        error_code: int | None = None,
        reset_by_peer: bool = False,
    ):
        super().__init__(message, stream_id, error_code)
        self.reset_by_peer = reset_by_peer


class WebRTCStreamTimeoutError(WebRTCStreamError):
    """Stream operation timed out."""

    pass


class WebRTCStreamStateError(WebRTCStreamError):
    """Invalid operation for current stream state."""

    def __init__(
        self,
        message: str,
        stream_id: str | None = None,
        current_state: str | None = None,
        attempted_operation: str | None = None,
    ):
        super().__init__(message, stream_id)
        self.current_state = current_state
        self.attempted_operation = attempted_operation

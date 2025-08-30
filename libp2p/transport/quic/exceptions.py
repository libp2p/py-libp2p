"""
QUIC Transport exceptions
"""

from typing import Any, Literal


class QUICError(Exception):
    """Base exception for all QUIC transport errors."""

    def __init__(self, message: str, error_code: int | None = None):
        super().__init__(message)
        self.error_code = error_code


# Transport-level exceptions


class QUICTransportError(QUICError):
    """Base exception for QUIC transport operations."""

    pass


class QUICDialError(QUICTransportError):
    """Error occurred during QUIC connection establishment."""

    pass


class QUICListenError(QUICTransportError):
    """Error occurred during QUIC listener operations."""

    pass


class QUICSecurityError(QUICTransportError):
    """Error related to QUIC security/TLS operations."""

    pass


# Connection-level exceptions


class QUICConnectionError(QUICError):
    """Base exception for QUIC connection operations."""

    pass


class QUICConnectionClosedError(QUICConnectionError):
    """QUIC connection has been closed."""

    pass


class QUICConnectionTimeoutError(QUICConnectionError):
    """QUIC connection operation timed out."""

    pass


class QUICHandshakeError(QUICConnectionError):
    """Error during QUIC handshake process."""

    pass


class QUICPeerVerificationError(QUICConnectionError):
    """Error verifying peer identity during handshake."""

    pass


# Stream-level exceptions


class QUICStreamError(QUICError):
    """Base exception for QUIC stream operations."""

    def __init__(
        self,
        message: str,
        stream_id: str | None = None,
        error_code: int | None = None,
    ):
        super().__init__(message, error_code)
        self.stream_id = stream_id


class QUICStreamClosedError(QUICStreamError):
    """Stream is closed and cannot be used for I/O operations."""

    pass


class QUICStreamResetError(QUICStreamError):
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


class QUICStreamTimeoutError(QUICStreamError):
    """Stream operation timed out."""

    pass


class QUICStreamBackpressureError(QUICStreamError):
    """Stream write blocked due to flow control."""

    pass


class QUICStreamLimitError(QUICStreamError):
    """Stream limit reached (too many concurrent streams)."""

    pass


class QUICStreamStateError(QUICStreamError):
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


# Flow control exceptions


class QUICFlowControlError(QUICError):
    """Base exception for flow control related errors."""

    pass


class QUICFlowControlViolationError(QUICFlowControlError):
    """Flow control limits were violated."""

    pass


class QUICFlowControlDeadlockError(QUICFlowControlError):
    """Flow control deadlock detected."""

    pass


# Resource management exceptions


class QUICResourceError(QUICError):
    """Base exception for resource management errors."""

    pass


class QUICMemoryLimitError(QUICResourceError):
    """Memory limit exceeded."""

    pass


class QUICConnectionLimitError(QUICResourceError):
    """Connection limit exceeded."""

    pass


# Multiaddr and addressing exceptions


class QUICAddressError(QUICError):
    """Base exception for QUIC addressing errors."""

    pass


class QUICInvalidMultiaddrError(QUICAddressError):
    """Invalid multiaddr format for QUIC transport."""

    pass


class QUICAddressResolutionError(QUICAddressError):
    """Failed to resolve QUIC address."""

    pass


class QUICProtocolError(QUICError):
    """Base exception for QUIC protocol errors."""

    pass


class QUICVersionNegotiationError(QUICProtocolError):
    """QUIC version negotiation failed."""

    pass


class QUICUnsupportedVersionError(QUICProtocolError):
    """Unsupported QUIC version."""

    pass


# Configuration exceptions


class QUICConfigurationError(QUICError):
    """Base exception for QUIC configuration errors."""

    pass


class QUICInvalidConfigError(QUICConfigurationError):
    """Invalid QUIC configuration parameters."""

    pass


class QUICCertificateError(QUICConfigurationError):
    """Error with TLS certificate configuration."""

    pass


def map_quic_error_code(error_code: int) -> str:
    """
    Map QUIC error codes to human-readable descriptions.
    Based on RFC 9000 Transport Error Codes.
    """
    error_codes = {
        0x00: "NO_ERROR",
        0x01: "INTERNAL_ERROR",
        0x02: "CONNECTION_REFUSED",
        0x03: "FLOW_CONTROL_ERROR",
        0x04: "STREAM_LIMIT_ERROR",
        0x05: "STREAM_STATE_ERROR",
        0x06: "FINAL_SIZE_ERROR",
        0x07: "FRAME_ENCODING_ERROR",
        0x08: "TRANSPORT_PARAMETER_ERROR",
        0x09: "CONNECTION_ID_LIMIT_ERROR",
        0x0A: "PROTOCOL_VIOLATION",
        0x0B: "INVALID_TOKEN",
        0x0C: "APPLICATION_ERROR",
        0x0D: "CRYPTO_BUFFER_EXCEEDED",
        0x0E: "KEY_UPDATE_ERROR",
        0x0F: "AEAD_LIMIT_REACHED",
        0x10: "NO_VIABLE_PATH",
    }

    return error_codes.get(error_code, f"UNKNOWN_ERROR_{error_code:02X}")


def create_stream_error(
    error_type: str,
    message: str,
    stream_id: str | None = None,
    error_code: int | None = None,
) -> QUICStreamError:
    """
    Factory function to create appropriate stream error based on type.

    Args:
        error_type: Type of error ("closed", "reset", "timeout", "backpressure", etc.)
        message: Error message
        stream_id: Stream identifier
        error_code: QUIC error code

    Returns:
        Appropriate QUICStreamError subclass

    """
    error_type = error_type.lower()

    if error_type in ("closed", "close"):
        return QUICStreamClosedError(message, stream_id, error_code)
    elif error_type == "reset":
        return QUICStreamResetError(message, stream_id, error_code)
    elif error_type == "timeout":
        return QUICStreamTimeoutError(message, stream_id, error_code)
    elif error_type in ("backpressure", "flow_control"):
        return QUICStreamBackpressureError(message, stream_id, error_code)
    elif error_type in ("limit", "stream_limit"):
        return QUICStreamLimitError(message, stream_id, error_code)
    elif error_type == "state":
        return QUICStreamStateError(message, stream_id)
    else:
        return QUICStreamError(message, stream_id, error_code)


def create_connection_error(
    error_type: str, message: str, error_code: int | None = None
) -> QUICConnectionError:
    """
    Factory function to create appropriate connection error based on type.

    Args:
        error_type: Type of error ("closed", "timeout", "handshake", etc.)
        message: Error message
        error_code: QUIC error code

    Returns:
        Appropriate QUICConnectionError subclass

    """
    error_type = error_type.lower()

    if error_type in ("closed", "close"):
        return QUICConnectionClosedError(message, error_code)
    elif error_type == "timeout":
        return QUICConnectionTimeoutError(message, error_code)
    elif error_type == "handshake":
        return QUICHandshakeError(message, error_code)
    elif error_type in ("peer_verification", "verification"):
        return QUICPeerVerificationError(message, error_code)
    else:
        return QUICConnectionError(message, error_code)


class QUICErrorContext:
    """
    Context manager for handling QUIC errors with automatic error mapping.
    Useful for converting low-level aioquic errors to py-libp2p QUIC errors.
    """

    def __init__(self, operation: str, component: str = "quic") -> None:
        self.operation = operation
        self.component = component

    def __enter__(self) -> "QUICErrorContext":
        return self

    # TODO: Fix types for exc_type
    def __exit__(
        self,
        exc_type: type[BaseException] | None | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        if exc_type is None:
            return False

        if exc_val is None:
            return False

        # Map common aioquic exceptions to our exceptions
        if "ConnectionClosed" in str(exc_type):
            raise QUICConnectionClosedError(
                f"Connection closed during {self.operation}: {exc_val}"
            ) from exc_val
        elif "StreamReset" in str(exc_type):
            raise QUICStreamResetError(
                f"Stream reset during {self.operation}: {exc_val}"
            ) from exc_val
        elif "timeout" in str(exc_val).lower():
            if "stream" in self.component.lower():
                raise QUICStreamTimeoutError(
                    f"Timeout during {self.operation}: {exc_val}"
                ) from exc_val
            else:
                raise QUICConnectionTimeoutError(
                    f"Timeout during {self.operation}: {exc_val}"
                ) from exc_val
        elif "flow control" in str(exc_val).lower():
            raise QUICStreamBackpressureError(
                f"Flow control error during {self.operation}: {exc_val}"
            ) from exc_val

        # Let other exceptions propagate
        return False

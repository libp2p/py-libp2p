from libp2p.exceptions import (
    BaseLibp2pError,
)


class IOException(BaseLibp2pError):
    pass


class ConnectionClosedError(IOException):
    """
    Raised when a connection is closed by the peer.

    Carries structured close information so that upstream code can make
    decisions based on exception type (``except ConnectionClosedError``)
    rather than fragile string matching on the message.
    """

    def __init__(
        self,
        message: str,
        close_code: int | None = None,
        close_reason: str = "",
        transport: str = "",
    ) -> None:
        super().__init__(message)
        self.close_code = close_code
        self.close_reason = close_reason
        self.transport = transport


class IncompleteReadError(IOException):
    """Fewer bytes were read than requested."""

    def __init__(
        self,
        message: str,
        expected_bytes: int = 0,
        received_bytes: int = 0,
    ) -> None:
        super().__init__(message)
        self.expected_bytes = expected_bytes
        self.received_bytes = received_bytes

    @property
    def is_clean_close(self) -> bool:
        """Returns True if this represents a clean connection closure."""
        return self.received_bytes == 0


class MsgioException(IOException):
    pass


class MissingLengthException(MsgioException):
    pass


class MissingMessageException(MsgioException):
    pass


class DecryptionFailedException(MsgioException):
    pass


class MessageTooLarge(MsgioException):
    pass

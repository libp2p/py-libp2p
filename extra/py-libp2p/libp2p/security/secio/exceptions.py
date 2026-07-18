from libp2p.security.exceptions import (
    HandshakeFailure,
)


class SecioException(HandshakeFailure):
    pass


class SelfEncryption(SecioException):
    """
    Raised to indicate that a host is attempting to encrypt communications
    with itself.
    """


class PeerMismatchException(SecioException):
    pass


class InvalidSignatureOnExchange(SecioException):
    pass


class IncompatibleChoices(SecioException):
    pass


class InconsistentNonce(SecioException):
    pass


class SedesException(SecioException):
    pass

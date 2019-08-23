class SecioException(Exception):
    pass


class SelfEncryption(SecioException):
    """
    Raised to indicate that a host is attempting to encrypt communications
    with itself.
    """

    pass


class PeerMismatchException(SecioException):
    pass


class InvalidSignatureOnExchange(SecioException):
    pass


class HandshakeFailed(SecioException):
    pass


class IncompatibleChoices(SecioException):
    pass

class SecioException(Exception):
    pass


class PeerMismatchException(SecioException):
    pass


class InvalidSignatureOnExchange(SecioException):
    pass


class HandshakeFailed(SecioException):
    pass

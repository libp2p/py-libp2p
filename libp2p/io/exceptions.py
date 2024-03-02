from libp2p.exceptions import (
    BaseLibp2pError,
)


class IOException(BaseLibp2pError):
    pass


class IncompleteReadError(IOException):
    """Fewer bytes were read than requested."""


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

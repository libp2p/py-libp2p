from libp2p.exceptions import BaseLibp2pError


class MsgioException(BaseLibp2pError):
    pass


class MissingLengthException(MsgioException):
    pass


class MissingMessageException(MsgioException):
    pass

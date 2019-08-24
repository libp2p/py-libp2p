class MsgioException(Exception):
    pass


class MissingLengthException(MsgioException):
    pass


class MissingMessageException(MsgioException):
    pass

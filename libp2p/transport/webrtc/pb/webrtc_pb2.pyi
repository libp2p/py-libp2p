from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Message(_message.Message):
    __slots__ = ("flag", "message")
    class Flag(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        FIN: _ClassVar[Message.Flag]
        STOP_SENDING: _ClassVar[Message.Flag]
        RESET: _ClassVar[Message.Flag]
        FIN_ACK: _ClassVar[Message.Flag]
    FIN: Message.Flag
    STOP_SENDING: Message.Flag
    RESET: Message.Flag
    FIN_ACK: Message.Flag
    FLAG_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    flag: Message.Flag
    message: bytes
    def __init__(self, flag: _Optional[_Union[Message.Flag, str]] = ..., message: _Optional[bytes] = ...) -> None: ...

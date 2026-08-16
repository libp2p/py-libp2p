from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SignalingMessage(_message.Message):
    __slots__ = ("type", "data")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SDP_OFFER: _ClassVar[SignalingMessage.Type]
        SDP_ANSWER: _ClassVar[SignalingMessage.Type]
        ICE_CANDIDATE: _ClassVar[SignalingMessage.Type]
        ICE_DONE: _ClassVar[SignalingMessage.Type]
    SDP_OFFER: SignalingMessage.Type
    SDP_ANSWER: SignalingMessage.Type
    ICE_CANDIDATE: SignalingMessage.Type
    ICE_DONE: SignalingMessage.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: SignalingMessage.Type
    data: bytes
    def __init__(self, type: _Optional[_Union[SignalingMessage.Type, str]] = ..., data: _Optional[bytes] = ...) -> None: ...

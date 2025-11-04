from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class HopMessage(_message.Message):
    __slots__ = ("type", "peer", "reservation", "limit", "status", "senderRecord")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        RESERVE: _ClassVar[HopMessage.Type]
        CONNECT: _ClassVar[HopMessage.Type]
        STATUS: _ClassVar[HopMessage.Type]
    RESERVE: HopMessage.Type
    CONNECT: HopMessage.Type
    STATUS: HopMessage.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PEER_FIELD_NUMBER: _ClassVar[int]
    RESERVATION_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SENDERRECORD_FIELD_NUMBER: _ClassVar[int]
    type: HopMessage.Type
    peer: bytes
    reservation: Reservation
    limit: Limit
    status: Status
    senderRecord: bytes
    def __init__(self, type: _Optional[_Union[HopMessage.Type, str]] = ..., peer: _Optional[bytes] = ..., reservation: _Optional[_Union[Reservation, _Mapping]] = ..., limit: _Optional[_Union[Limit, _Mapping]] = ..., status: _Optional[_Union[Status, _Mapping]] = ..., senderRecord: _Optional[bytes] = ...) -> None: ... #type: ignore

class StopMessage(_message.Message):
    __slots__ = ("type", "peer", "status", "senderRecord")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        CONNECT: _ClassVar[StopMessage.Type]
        STATUS: _ClassVar[StopMessage.Type]
    CONNECT: StopMessage.Type
    STATUS: StopMessage.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PEER_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SENDERRECORD_FIELD_NUMBER: _ClassVar[int]
    type: StopMessage.Type
    peer: bytes
    status: Status
    senderRecord: bytes
    def __init__(self, type: _Optional[_Union[StopMessage.Type, str]] = ..., peer: _Optional[bytes] = ..., status: _Optional[_Union[Status, _Mapping]] = ..., senderRecord: _Optional[bytes] = ...) -> None: ... #type: ignore

class Reservation(_message.Message):
    __slots__ = ("voucher", "signature", "expire")
    VOUCHER_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    EXPIRE_FIELD_NUMBER: _ClassVar[int]
    voucher: bytes
    signature: bytes
    expire: int
    def __init__(self, voucher: _Optional[bytes] = ..., signature: _Optional[bytes] = ..., expire: _Optional[int] = ...) -> None: ...

class Limit(_message.Message):
    __slots__ = ("duration", "data")
    DURATION_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    duration: int
    data: int
    def __init__(self, duration: _Optional[int] = ..., data: _Optional[int] = ...) -> None: ...

class Status(_message.Message):
    __slots__ = ("code", "message")
    class Code(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OK: _ClassVar[Status.Code]
        RESERVATION_REFUSED: _ClassVar[Status.Code]
        RESOURCE_LIMIT_EXCEEDED: _ClassVar[Status.Code]
        PERMISSION_DENIED: _ClassVar[Status.Code]
        CONNECTION_FAILED: _ClassVar[Status.Code]
        DIAL_REFUSED: _ClassVar[Status.Code]
        STOP_FAILED: _ClassVar[Status.Code]
        MALFORMED_MESSAGE: _ClassVar[Status.Code]
    OK: Status.Code
    RESERVATION_REFUSED: Status.Code
    RESOURCE_LIMIT_EXCEEDED: Status.Code
    PERMISSION_DENIED: Status.Code
    CONNECTION_FAILED: Status.Code
    DIAL_REFUSED: Status.Code
    STOP_FAILED: Status.Code
    MALFORMED_MESSAGE: Status.Code
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: Status.Code
    message: str
    def __init__(self, code: _Optional[_Union[Status.Code, str]] = ..., message: _Optional[str] = ...) -> None: ...

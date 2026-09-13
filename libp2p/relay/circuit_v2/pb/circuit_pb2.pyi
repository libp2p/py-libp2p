from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import Any as _Any, ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    UNUSED: _ClassVar[Status]
    OK: _ClassVar[Status]
    RESERVATION_REFUSED: _ClassVar[Status]
    RESOURCE_LIMIT_EXCEEDED: _ClassVar[Status]
    PERMISSION_DENIED: _ClassVar[Status]
    CONNECTION_FAILED: _ClassVar[Status]
    NO_RESERVATION: _ClassVar[Status]
    MALFORMED_MESSAGE: _ClassVar[Status]
    UNEXPECTED_MESSAGE: _ClassVar[Status]
UNUSED: Status
OK: Status
RESERVATION_REFUSED: Status
RESOURCE_LIMIT_EXCEEDED: Status
PERMISSION_DENIED: Status
CONNECTION_FAILED: Status
NO_RESERVATION: Status
MALFORMED_MESSAGE: Status
UNEXPECTED_MESSAGE: Status

class PeerId(_message.Message):
    __slots__ = ("id", "addrs")
    ID_FIELD_NUMBER: _ClassVar[int]
    ADDRS_FIELD_NUMBER: _ClassVar[int]
    id: bytes
    addrs: _containers.RepeatedScalarFieldContainer[bytes]
    def __init__(self, id: _Optional[bytes] = ..., addrs: _Optional[_Iterable[bytes]] = ...) -> None: ...

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
    peer: PeerId
    reservation: Reservation
    limit: Limit
    status: Status
    senderRecord: bytes
    def __init__(self, type: _Optional[_Union[HopMessage.Type, str]] = ..., peer: _Optional[_Union[PeerId, _Mapping[str, _Any]]] = ..., reservation: _Optional[_Union[Reservation, _Mapping[str, _Any]]] = ..., limit: _Optional[_Union[Limit, _Mapping[str, _Any]]] = ..., status: _Optional[_Union[Status, str]] = ..., senderRecord: _Optional[bytes] = ...) -> None: ...

class StopMessage(_message.Message):
    __slots__ = ("type", "peer", "limit", "status")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        CONNECT: _ClassVar[StopMessage.Type]
        STATUS: _ClassVar[StopMessage.Type]
    CONNECT: StopMessage.Type
    STATUS: StopMessage.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PEER_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    type: StopMessage.Type
    peer: PeerId
    limit: Limit
    status: Status
    def __init__(self, type: _Optional[_Union[StopMessage.Type, str]] = ..., peer: _Optional[_Union[PeerId, _Mapping[str, _Any]]] = ..., limit: _Optional[_Union[Limit, _Mapping[str, _Any]]] = ..., status: _Optional[_Union[Status, str]] = ...) -> None: ...

class Reservation(_message.Message):
    __slots__ = ("expire", "addrs", "voucher")
    EXPIRE_FIELD_NUMBER: _ClassVar[int]
    ADDRS_FIELD_NUMBER: _ClassVar[int]
    VOUCHER_FIELD_NUMBER: _ClassVar[int]
    expire: int
    addrs: _containers.RepeatedScalarFieldContainer[bytes]
    voucher: bytes
    def __init__(self, expire: _Optional[int] = ..., addrs: _Optional[_Iterable[bytes]] = ..., voucher: _Optional[bytes] = ...) -> None: ...

class Limit(_message.Message):
    __slots__ = ("duration", "data")
    DURATION_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    duration: int
    data: int
    def __init__(self, duration: _Optional[int] = ..., data: _Optional[int] = ...) -> None: ...

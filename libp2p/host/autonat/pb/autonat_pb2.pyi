from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import Any as _Any, ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DIAL: _ClassVar[Type]
    DIAL_RESPONSE: _ClassVar[Type]

class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OK: _ClassVar[Status]
    E_DIAL_ERROR: _ClassVar[Status]
    E_DIAL_REFUSED: _ClassVar[Status]
    E_BAD_REQUEST: _ClassVar[Status]
    E_INTERNAL_ERROR: _ClassVar[Status]
DIAL: Type
DIAL_RESPONSE: Type
OK: Status
E_DIAL_ERROR: Status
E_DIAL_REFUSED: Status
E_BAD_REQUEST: Status
E_INTERNAL_ERROR: Status

class Message(_message.Message):
    __slots__ = ("type", "dial", "dial_response")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DIAL_FIELD_NUMBER: _ClassVar[int]
    DIAL_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    type: Type
    dial: DialRequest
    dial_response: DialResponse
    def __init__(self, type: _Optional[_Union[Type, str]] = ..., dial: _Optional[_Union[DialRequest, _Mapping[str, _Any]]] = ..., dial_response: _Optional[_Union[DialResponse, _Mapping[str, _Any]]] = ...) -> None: ...

class DialRequest(_message.Message):
    __slots__ = ("peer",)
    PEER_FIELD_NUMBER: _ClassVar[int]
    peer: PeerInfo
    def __init__(self, peer: _Optional[_Union[PeerInfo, _Mapping[str, _Any]]] = ...) -> None: ...

class DialResponse(_message.Message):
    __slots__ = ("status", "statusText", "addr")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STATUSTEXT_FIELD_NUMBER: _ClassVar[int]
    ADDR_FIELD_NUMBER: _ClassVar[int]
    status: Status
    statusText: str
    addr: bytes
    def __init__(self, status: _Optional[_Union[Status, str]] = ..., statusText: _Optional[str] = ..., addr: _Optional[bytes] = ...) -> None: ...

class PeerInfo(_message.Message):
    __slots__ = ("id", "addrs")
    ID_FIELD_NUMBER: _ClassVar[int]
    ADDRS_FIELD_NUMBER: _ClassVar[int]
    id: bytes
    addrs: _containers.RepeatedScalarFieldContainer[bytes]
    def __init__(self, id: _Optional[bytes] = ..., addrs: _Optional[_Iterable[bytes]] = ...) -> None: ...

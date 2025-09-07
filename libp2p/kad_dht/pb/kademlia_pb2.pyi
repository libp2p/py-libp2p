from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Record(_message.Message):
    __slots__ = ("key", "value", "timeReceived")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    TIMERECEIVED_FIELD_NUMBER: _ClassVar[int]
    key: bytes
    value: bytes
    timeReceived: str
    def __init__(self, key: _Optional[bytes] = ..., value: _Optional[bytes] = ..., timeReceived: _Optional[str] = ...) -> None: ...

class Message(_message.Message):
    __slots__ = ("type", "clusterLevelRaw", "key", "record", "closerPeers", "providerPeers", "senderRecord")
    class MessageType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        PUT_VALUE: _ClassVar[Message.MessageType]
        GET_VALUE: _ClassVar[Message.MessageType]
        ADD_PROVIDER: _ClassVar[Message.MessageType]
        GET_PROVIDERS: _ClassVar[Message.MessageType]
        FIND_NODE: _ClassVar[Message.MessageType]
        PING: _ClassVar[Message.MessageType]
    PUT_VALUE: Message.MessageType
    GET_VALUE: Message.MessageType
    ADD_PROVIDER: Message.MessageType
    GET_PROVIDERS: Message.MessageType
    FIND_NODE: Message.MessageType
    PING: Message.MessageType
    class ConnectionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        NOT_CONNECTED: _ClassVar[Message.ConnectionType]
        CONNECTED: _ClassVar[Message.ConnectionType]
        CAN_CONNECT: _ClassVar[Message.ConnectionType]
        CANNOT_CONNECT: _ClassVar[Message.ConnectionType]
    NOT_CONNECTED: Message.ConnectionType
    CONNECTED: Message.ConnectionType
    CAN_CONNECT: Message.ConnectionType
    CANNOT_CONNECT: Message.ConnectionType
    class Peer(_message.Message):
        __slots__ = ("id", "addrs", "connection", "signedRecord")
        ID_FIELD_NUMBER: _ClassVar[int]
        ADDRS_FIELD_NUMBER: _ClassVar[int]
        CONNECTION_FIELD_NUMBER: _ClassVar[int]
        SIGNEDRECORD_FIELD_NUMBER: _ClassVar[int]
        id: bytes
        addrs: _containers.RepeatedScalarFieldContainer[bytes]
        connection: Message.ConnectionType
        signedRecord: bytes
        def __init__(self, id: _Optional[bytes] = ..., addrs: _Optional[_Iterable[bytes]] = ..., connection: _Optional[_Union[Message.ConnectionType, str]] = ..., signedRecord: _Optional[bytes] = ...) -> None: ...
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CLUSTERLEVELRAW_FIELD_NUMBER: _ClassVar[int]
    KEY_FIELD_NUMBER: _ClassVar[int]
    RECORD_FIELD_NUMBER: _ClassVar[int]
    CLOSERPEERS_FIELD_NUMBER: _ClassVar[int]
    PROVIDERPEERS_FIELD_NUMBER: _ClassVar[int]
    SENDERRECORD_FIELD_NUMBER: _ClassVar[int]
    type: Message.MessageType
    clusterLevelRaw: int
    key: bytes
    record: Record
    closerPeers: _containers.RepeatedCompositeFieldContainer[Message.Peer]
    providerPeers: _containers.RepeatedCompositeFieldContainer[Message.Peer]
    senderRecord: bytes
    def __init__(self, type: _Optional[_Union[Message.MessageType, str]] = ..., clusterLevelRaw: _Optional[int] = ..., key: _Optional[bytes] = ..., record: _Optional[_Union[Record, _Mapping]] = ..., closerPeers: _Optional[_Iterable[_Union[Message.Peer, _Mapping]]] = ..., providerPeers: _Optional[_Iterable[_Union[Message.Peer, _Mapping]]] = ..., senderRecord: _Optional[bytes] = ...) -> None: ...   # type: ignore 

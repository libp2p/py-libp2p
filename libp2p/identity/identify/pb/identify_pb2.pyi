from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Identify(_message.Message):
    __slots__ = ("protocol_version", "agent_version", "public_key", "listen_addrs", "observed_addr", "protocols", "signedPeerRecord")
    PROTOCOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    AGENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    LISTEN_ADDRS_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_ADDR_FIELD_NUMBER: _ClassVar[int]
    PROTOCOLS_FIELD_NUMBER: _ClassVar[int]
    SIGNEDPEERRECORD_FIELD_NUMBER: _ClassVar[int]
    protocol_version: str
    agent_version: str
    public_key: bytes
    listen_addrs: _containers.RepeatedScalarFieldContainer[bytes]
    observed_addr: bytes
    protocols: _containers.RepeatedScalarFieldContainer[str]
    signedPeerRecord: bytes
    def __init__(self, protocol_version: _Optional[str] = ..., agent_version: _Optional[str] = ..., public_key: _Optional[bytes] = ..., listen_addrs: _Optional[_Iterable[bytes]] = ..., observed_addr: _Optional[bytes] = ..., protocols: _Optional[_Iterable[str]] = ..., signedPeerRecord: _Optional[bytes] = ...) -> None: ...

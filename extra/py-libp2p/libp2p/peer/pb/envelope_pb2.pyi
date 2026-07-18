from libp2p.peer.pb import crypto_pb2 as _crypto_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Envelope(_message.Message):
    __slots__ = ("public_key", "payload_type", "payload", "signature")
    PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    public_key: _crypto_pb2.PublicKey
    payload_type: bytes
    payload: bytes
    signature: bytes
    def __init__(self, public_key: _Optional[_Union[_crypto_pb2.PublicKey, _Mapping]] = ..., payload_type: _Optional[bytes] = ..., payload: _Optional[bytes] = ..., signature: _Optional[bytes] = ...) -> None: ... # type: ignore[type-arg]

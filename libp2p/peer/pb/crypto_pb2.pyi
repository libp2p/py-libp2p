from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class KeyType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RSA: _ClassVar[KeyType]
    Ed25519: _ClassVar[KeyType]
    Secp256k1: _ClassVar[KeyType]
    ECDSA: _ClassVar[KeyType]
RSA: KeyType
Ed25519: KeyType
Secp256k1: KeyType
ECDSA: KeyType

class PublicKey(_message.Message):
    __slots__ = ("Type", "Data")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    Type: KeyType
    Data: bytes
    def __init__(self, Type: _Optional[_Union[KeyType, str]] = ..., Data: _Optional[bytes] = ...) -> None: ...

class PrivateKey(_message.Message):
    __slots__ = ("Type", "Data")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    Type: KeyType
    Data: bytes
    def __init__(self, Type: _Optional[_Union[KeyType, str]] = ..., Data: _Optional[bytes] = ...) -> None: ...

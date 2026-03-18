from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class IpnsEntry(_message.Message):
    __slots__ = (
        "value",
        "signatureV1",
        "validityType",
        "validity",
        "sequence",
        "ttl",
        "pubKey",
        "signatureV2",
        "data",
    )

    class ValidityType:
        EOL: _ClassVar[int]

    VALUE_FIELD_NUMBER: _ClassVar[int]
    SIGNATUREV1_FIELD_NUMBER: _ClassVar[int]
    VALIDITYTYPE_FIELD_NUMBER: _ClassVar[int]
    VALIDITY_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    TTL_FIELD_NUMBER: _ClassVar[int]
    PUBKEY_FIELD_NUMBER: _ClassVar[int]
    SIGNATUREV2_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]

    value: bytes
    signatureV1: bytes
    validityType: int
    validity: bytes
    sequence: int
    ttl: int
    pubKey: bytes
    signatureV2: bytes
    data: bytes

    def __init__(
        self,
        value: _Optional[bytes] = ...,
        signatureV1: _Optional[bytes] = ...,
        validityType: _Optional[int] = ...,
        validity: _Optional[bytes] = ...,
        sequence: _Optional[int] = ...,
        ttl: _Optional[int] = ...,
        pubKey: _Optional[bytes] = ...,
        signatureV2: _Optional[bytes] = ...,
        data: _Optional[bytes] = ...,
    ) -> None: ...

"""
Types for ``circuit_pb2`` (aligned with ``circuit.proto`` / generated runtime).

Edit when the ``.proto`` changes; keep in sync with mypy-protobuf patterns.
isort:skip_file
"""

import builtins
import collections.abc
import google.protobuf.descriptor
import google.protobuf.internal.containers
import google.protobuf.internal.enum_type_wrapper
import google.protobuf.message
import sys
import typing

if sys.version_info >= (3, 10):
    import typing as typing_extensions
else:
    import typing_extensions

DESCRIPTOR: google.protobuf.descriptor.FileDescriptor

class _Status:
    ValueType = typing.NewType("ValueType", builtins.int)
    V: typing_extensions.TypeAlias = ValueType

class _StatusEnumTypeWrapper(google.protobuf.internal.enum_type_wrapper._EnumTypeWrapper[_Status.ValueType], builtins.type):
    DESCRIPTOR: google.protobuf.descriptor.EnumDescriptor
    UNUSED: _Status.ValueType  # 0
    OK: _Status.ValueType  # 100
    RESERVATION_REFUSED: _Status.ValueType  # 200
    RESOURCE_LIMIT_EXCEEDED: _Status.ValueType  # 201
    PERMISSION_DENIED: _Status.ValueType  # 202
    CONNECTION_FAILED: _Status.ValueType  # 203
    NO_RESERVATION: _Status.ValueType  # 204
    MALFORMED_MESSAGE: _Status.ValueType  # 400
    UNEXPECTED_MESSAGE: _Status.ValueType  # 401

class Status(_Status, metaclass=_StatusEnumTypeWrapper): ...
UNUSED: Status.ValueType  # 0
OK: Status.ValueType  # 100
RESERVATION_REFUSED: Status.ValueType  # 200
RESOURCE_LIMIT_EXCEEDED: Status.ValueType  # 201
PERMISSION_DENIED: Status.ValueType  # 202
CONNECTION_FAILED: Status.ValueType  # 203
NO_RESERVATION: Status.ValueType  # 204
MALFORMED_MESSAGE: Status.ValueType  # 400
UNEXPECTED_MESSAGE: Status.ValueType  # 401
global___Status = Status

@typing.final
class Peer(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor

    ID_FIELD_NUMBER: builtins.int
    ADDRS_FIELD_NUMBER: builtins.int
    id: builtins.bytes
    @property
    def addrs(self) -> google.protobuf.internal.containers.RepeatedScalarFieldContainer[builtins.bytes]: ...
    def __init__(
        self,
        *,
        id: builtins.bytes | None = ...,
        addrs: collections.abc.Iterable[builtins.bytes] | None = ...,
    ) -> None: ...
    def HasField(self, field_name: typing.Literal["id", b"id"]) -> builtins.bool: ...
    def ClearField(self, field_name: typing.Literal["addrs", b"addrs", "id", b"id"]) -> None: ...

global___Peer = Peer

@typing.final
class Reservation(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor

    EXPIRE_FIELD_NUMBER: builtins.int
    ADDRS_FIELD_NUMBER: builtins.int
    VOUCHER_FIELD_NUMBER: builtins.int
    SIGNATURE_FIELD_NUMBER: builtins.int
    expire: builtins.int
    voucher: builtins.bytes
    signature: builtins.bytes
    @property
    def addrs(self) -> google.protobuf.internal.containers.RepeatedScalarFieldContainer[builtins.bytes]: ...
    def __init__(
        self,
        *,
        expire: builtins.int | None = ...,
        addrs: collections.abc.Iterable[builtins.bytes] | None = ...,
        voucher: builtins.bytes | None = ...,
        signature: builtins.bytes | None = ...,
    ) -> None: ...
    def HasField(self, field_name: typing.Literal["_expire", b"_expire", "_signature", b"_signature", "_voucher", b"_voucher", "expire", b"expire", "signature", b"signature", "voucher", b"voucher"]) -> builtins.bool: ...
    def ClearField(self, field_name: typing.Literal["addrs", b"addrs", "expire", b"expire", "signature", b"signature", "voucher", b"voucher"]) -> None: ...

global___Reservation = Reservation

@typing.final
class Limit(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor

    DURATION_FIELD_NUMBER: builtins.int
    DATA_FIELD_NUMBER: builtins.int
    duration: builtins.int
    data: builtins.int
    def __init__(
        self,
        *,
        duration: builtins.int | None = ...,
        data: builtins.int | None = ...,
    ) -> None: ...
    def HasField(self, field_name: typing.Literal["_data", b"_data", "_duration", b"_duration", "data", b"data", "duration", b"duration"]) -> builtins.bool: ...
    def ClearField(self, field_name: typing.Literal["data", b"data", "duration", b"duration"]) -> None: ...

global___Limit = Limit

@typing.final
class HopMessage(google.protobuf.message.Message):
    """Circuit v2 hop stream messages."""

    DESCRIPTOR: google.protobuf.descriptor.Descriptor

    class _Type:
        ValueType = typing.NewType("ValueType", builtins.int)
        V: typing_extensions.TypeAlias = ValueType

    class _TypeEnumTypeWrapper(google.protobuf.internal.enum_type_wrapper._EnumTypeWrapper[HopMessage._Type.ValueType], builtins.type):
        DESCRIPTOR: google.protobuf.descriptor.EnumDescriptor
        RESERVE: HopMessage._Type.ValueType  # 0
        CONNECT: HopMessage._Type.ValueType  # 1
        STATUS: HopMessage._Type.ValueType  # 2

    class Type(_Type, metaclass=_TypeEnumTypeWrapper): ...
    RESERVE: HopMessage.Type.ValueType  # 0
    CONNECT: HopMessage.Type.ValueType  # 1
    STATUS: HopMessage.Type.ValueType  # 2

    TYPE_FIELD_NUMBER: builtins.int
    PEER_FIELD_NUMBER: builtins.int
    RESERVATION_FIELD_NUMBER: builtins.int
    LIMIT_FIELD_NUMBER: builtins.int
    STATUS_FIELD_NUMBER: builtins.int
    SENDERRECORD_FIELD_NUMBER: builtins.int
    type: HopMessage.Type.ValueType
    peer: global___Peer
    senderRecord: builtins.bytes
    @property
    def reservation(self) -> global___Reservation: ...
    @property
    def limit(self) -> global___Limit: ...
    status: global___Status.ValueType
    def __init__(
        self,
        *,
        type: HopMessage.Type.ValueType | None = ...,
        peer: global___Peer | None = ...,
        reservation: global___Reservation | None = ...,
        limit: global___Limit | None = ...,
        status: builtins.int | global___Status.ValueType | None = ...,
        senderRecord: builtins.bytes | None = ...,
    ) -> None: ...
    def HasField(self, field_name: typing.Literal["_peer", b"_peer", "_reservation", b"_reservation", "_senderRecord", b"_senderRecord", "limit", b"limit", "peer", b"peer", "reservation", b"reservation", "senderRecord", b"senderRecord", "status", b"status", "type", b"type"]) -> builtins.bool: ...
    def ClearField(self, field_name: typing.Literal["_peer", b"_peer", "_reservation", b"_reservation", "_senderRecord", b"_senderRecord", "limit", b"limit", "peer", b"peer", "reservation", b"reservation", "senderRecord", b"senderRecord", "status", b"status", "type", b"type"]) -> None: ...
    def WhichOneof(self, oneof_group: typing.Literal["_senderRecord", b"_senderRecord"]) -> typing.Literal["senderRecord"] | None: ...

global___HopMessage = HopMessage

@typing.final
class StopMessage(google.protobuf.message.Message):
    DESCRIPTOR: google.protobuf.descriptor.Descriptor

    class _Type:
        ValueType = typing.NewType("ValueType", builtins.int)
        V: typing_extensions.TypeAlias = ValueType

    class _TypeEnumTypeWrapper(google.protobuf.internal.enum_type_wrapper._EnumTypeWrapper[StopMessage._Type.ValueType], builtins.type):
        DESCRIPTOR: google.protobuf.descriptor.EnumDescriptor
        CONNECT: StopMessage._Type.ValueType  # 0
        STATUS: StopMessage._Type.ValueType  # 1

    class Type(_Type, metaclass=_TypeEnumTypeWrapper): ...
    CONNECT: StopMessage.Type.ValueType  # 0
    STATUS: StopMessage.Type.ValueType  # 1

    TYPE_FIELD_NUMBER: builtins.int
    PEER_FIELD_NUMBER: builtins.int
    LIMIT_FIELD_NUMBER: builtins.int
    STATUS_FIELD_NUMBER: builtins.int
    SENDERRECORD_FIELD_NUMBER: builtins.int
    type: StopMessage.Type.ValueType
    peer: global___Peer
    senderRecord: builtins.bytes
    @property
    def limit(self) -> global___Limit: ...
    status: global___Status.ValueType
    def __init__(
        self,
        *,
        type: StopMessage.Type.ValueType | None = ...,
        peer: global___Peer | None = ...,
        limit: global___Limit | None = ...,
        status: builtins.int | global___Status.ValueType | None = ...,
        senderRecord: builtins.bytes | None = ...,
    ) -> None: ...
    def HasField(self, field_name: typing.Literal["_limit", b"_limit", "_peer", b"_peer", "_senderRecord", b"_senderRecord", "limit", b"limit", "peer", b"peer", "senderRecord", b"senderRecord", "status", b"status", "type", b"type"]) -> builtins.bool: ...
    def ClearField(self, field_name: typing.Literal["_limit", b"_limit", "_peer", b"_peer", "_senderRecord", b"_senderRecord", "limit", b"limit", "peer", b"peer", "senderRecord", b"senderRecord", "status", b"status", "type", b"type"]) -> None: ...
    def WhichOneof(self, oneof_group: typing.Literal["_senderRecord", b"_senderRecord"]) -> typing.Literal["senderRecord"] | None: ...

global___StopMessage = StopMessage

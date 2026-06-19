from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union, Any as _Any

DESCRIPTOR: _descriptor.FileDescriptor

class Message(_message.Message):
    __slots__ = ("wantlist", "blocks", "payload", "blockPresences", "pendingBytes", "payment_terms", "tx_receipts", "payment_receipts", "payment_rejections")
    class BlockPresenceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Have: _ClassVar[Message.BlockPresenceType]
        DontHave: _ClassVar[Message.BlockPresenceType]
        PaymentRequired: _ClassVar[Message.BlockPresenceType]
    Have: Message.BlockPresenceType
    DontHave: Message.BlockPresenceType
    PaymentRequired: Message.BlockPresenceType
    class Wantlist(_message.Message):
        __slots__ = ("entries", "full")
        class WantType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            Block: _ClassVar[Message.Wantlist.WantType]
            Have: _ClassVar[Message.Wantlist.WantType]
        Block: Message.Wantlist.WantType
        Have: Message.Wantlist.WantType
        class Entry(_message.Message):
            __slots__ = ("block", "priority", "cancel", "wantType", "sendDontHave")
            BLOCK_FIELD_NUMBER: _ClassVar[int]
            PRIORITY_FIELD_NUMBER: _ClassVar[int]
            CANCEL_FIELD_NUMBER: _ClassVar[int]
            WANTTYPE_FIELD_NUMBER: _ClassVar[int]
            SENDDONTHAVE_FIELD_NUMBER: _ClassVar[int]
            block: bytes
            priority: int
            cancel: bool
            wantType: Message.Wantlist.WantType
            sendDontHave: bool
            def __init__(self, block: _Optional[bytes] = ..., priority: _Optional[int] = ..., cancel: bool = ..., wantType: _Optional[_Union[Message.Wantlist.WantType, str]] = ..., sendDontHave: bool = ...) -> None: ...
        ENTRIES_FIELD_NUMBER: _ClassVar[int]
        FULL_FIELD_NUMBER: _ClassVar[int]
        entries: _containers.RepeatedCompositeFieldContainer[Message.Wantlist.Entry]
        full: bool
        def __init__(self, entries: _Optional[_Iterable[_Union[Message.Wantlist.Entry, _Mapping[str, _Any]]]] = ..., full: bool = ...) -> None: ...
    class Block(_message.Message):
        __slots__ = ("prefix", "data")
        PREFIX_FIELD_NUMBER: _ClassVar[int]
        DATA_FIELD_NUMBER: _ClassVar[int]
        prefix: bytes
        data: bytes
        def __init__(self, prefix: _Optional[bytes] = ..., data: _Optional[bytes] = ...) -> None: ...
    class BlockPresence(_message.Message):
        __slots__ = ("cid", "type")
        CID_FIELD_NUMBER: _ClassVar[int]
        TYPE_FIELD_NUMBER: _ClassVar[int]
        cid: bytes
        type: Message.BlockPresenceType
        def __init__(self, cid: _Optional[bytes] = ..., type: _Optional[_Union[Message.BlockPresenceType, str]] = ...) -> None: ...
    class PaymentTerms(_message.Message):
        __slots__ = ("cid", "asset", "pay_to", "amount", "network", "block_size", "description")
        CID_FIELD_NUMBER: _ClassVar[int]
        ASSET_FIELD_NUMBER: _ClassVar[int]
        PAY_TO_FIELD_NUMBER: _ClassVar[int]
        AMOUNT_FIELD_NUMBER: _ClassVar[int]
        NETWORK_FIELD_NUMBER: _ClassVar[int]
        BLOCK_SIZE_FIELD_NUMBER: _ClassVar[int]
        DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
        cid: bytes
        asset: str
        pay_to: str
        amount: int
        network: str
        block_size: int
        description: str
        def __init__(self, cid: _Optional[bytes] = ..., asset: _Optional[str] = ..., pay_to: _Optional[str] = ..., amount: _Optional[int] = ..., network: _Optional[str] = ..., block_size: _Optional[int] = ..., description: _Optional[str] = ...) -> None: ...
    class TxReceipt(_message.Message):
        __slots__ = ("cid", "tx_hash", "from_address", "to_address", "amount", "asset", "network")
        CID_FIELD_NUMBER: _ClassVar[int]
        TX_HASH_FIELD_NUMBER: _ClassVar[int]
        FROM_ADDRESS_FIELD_NUMBER: _ClassVar[int]
        TO_ADDRESS_FIELD_NUMBER: _ClassVar[int]
        AMOUNT_FIELD_NUMBER: _ClassVar[int]
        ASSET_FIELD_NUMBER: _ClassVar[int]
        NETWORK_FIELD_NUMBER: _ClassVar[int]
        cid: bytes
        tx_hash: str
        from_address: str
        to_address: str
        amount: int
        asset: str
        network: str
        def __init__(self, cid: _Optional[bytes] = ..., tx_hash: _Optional[str] = ..., from_address: _Optional[str] = ..., to_address: _Optional[str] = ..., amount: _Optional[int] = ..., asset: _Optional[str] = ..., network: _Optional[str] = ...) -> None: ...
    class PaymentReceipt(_message.Message):
        __slots__ = ("cid", "tx_hash", "expires")
        CID_FIELD_NUMBER: _ClassVar[int]
        TX_HASH_FIELD_NUMBER: _ClassVar[int]
        EXPIRES_FIELD_NUMBER: _ClassVar[int]
        cid: bytes
        tx_hash: str
        expires: int
        def __init__(self, cid: _Optional[bytes] = ..., tx_hash: _Optional[str] = ..., expires: _Optional[int] = ...) -> None: ...
    class PaymentRejection(_message.Message):
        __slots__ = ("cid", "reason")
        CID_FIELD_NUMBER: _ClassVar[int]
        REASON_FIELD_NUMBER: _ClassVar[int]
        cid: bytes
        reason: str
        def __init__(self, cid: _Optional[bytes] = ..., reason: _Optional[str] = ...) -> None: ...
    WANTLIST_FIELD_NUMBER: _ClassVar[int]
    BLOCKS_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    BLOCKPRESENCES_FIELD_NUMBER: _ClassVar[int]
    PENDINGBYTES_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_TERMS_FIELD_NUMBER: _ClassVar[int]
    TX_RECEIPTS_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_RECEIPTS_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_REJECTIONS_FIELD_NUMBER: _ClassVar[int]
    wantlist: Message.Wantlist
    blocks: _containers.RepeatedScalarFieldContainer[bytes]
    payload: _containers.RepeatedCompositeFieldContainer[Message.Block]
    blockPresences: _containers.RepeatedCompositeFieldContainer[Message.BlockPresence]
    pendingBytes: int
    payment_terms: _containers.RepeatedCompositeFieldContainer[Message.PaymentTerms]
    tx_receipts: _containers.RepeatedCompositeFieldContainer[Message.TxReceipt]
    payment_receipts: _containers.RepeatedCompositeFieldContainer[Message.PaymentReceipt]
    payment_rejections: _containers.RepeatedCompositeFieldContainer[Message.PaymentRejection]
    def __init__(self, wantlist: _Optional[_Union[Message.Wantlist, _Mapping[str, _Any]]] = ..., blocks: _Optional[_Iterable[bytes]] = ..., payload: _Optional[_Iterable[_Union[Message.Block, _Mapping[str, _Any]]]] = ..., blockPresences: _Optional[_Iterable[_Union[Message.BlockPresence, _Mapping[str, _Any]]]] = ..., pendingBytes: _Optional[int] = ..., payment_terms: _Optional[_Iterable[_Union[Message.PaymentTerms, _Mapping[str, _Any]]]] = ..., tx_receipts: _Optional[_Iterable[_Union[Message.TxReceipt, _Mapping[str, _Any]]]] = ..., payment_receipts: _Optional[_Iterable[_Union[Message.PaymentReceipt, _Mapping[str, _Any]]]] = ..., payment_rejections: _Optional[_Iterable[_Union[Message.PaymentRejection, _Mapping[str, _Any]]]] = ...) -> None: ...

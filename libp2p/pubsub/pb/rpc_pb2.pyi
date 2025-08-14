from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RPC(_message.Message):
    __slots__ = ("subscriptions", "publish", "control", "senderRecord")
    class SubOpts(_message.Message):
        __slots__ = ("subscribe", "topicid")
        SUBSCRIBE_FIELD_NUMBER: _ClassVar[int]
        TOPICID_FIELD_NUMBER: _ClassVar[int]
        subscribe: bool
        topicid: str
        def __init__(self, subscribe: bool = ..., topicid: _Optional[str] = ...) -> None: ...
    SUBSCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    PUBLISH_FIELD_NUMBER: _ClassVar[int]
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    SENDERRECORD_FIELD_NUMBER: _ClassVar[int]
    subscriptions: _containers.RepeatedCompositeFieldContainer[RPC.SubOpts]
    publish: _containers.RepeatedCompositeFieldContainer[Message]
    control: ControlMessage
    senderRecord: bytes
    def __init__(self, subscriptions: _Optional[_Iterable[_Union[RPC.SubOpts, _Mapping]]] = ..., publish: _Optional[_Iterable[_Union[Message, _Mapping]]] = ..., control: _Optional[_Union[ControlMessage, _Mapping]] = ..., senderRecord: _Optional[bytes] = ...) -> None: ... # type: ignore

class Message(_message.Message):
    __slots__ = ("from_id", "data", "seqno", "topicIDs", "signature", "key")
    FROM_ID_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    SEQNO_FIELD_NUMBER: _ClassVar[int]
    TOPICIDS_FIELD_NUMBER: _ClassVar[int]
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    KEY_FIELD_NUMBER: _ClassVar[int]
    from_id: bytes
    data: bytes
    seqno: bytes
    topicIDs: _containers.RepeatedScalarFieldContainer[str]
    signature: bytes
    key: bytes
    def __init__(self, from_id: _Optional[bytes] = ..., data: _Optional[bytes] = ..., seqno: _Optional[bytes] = ..., topicIDs: _Optional[_Iterable[str]] = ..., signature: _Optional[bytes] = ..., key: _Optional[bytes] = ...) -> None: ...

class ControlMessage(_message.Message):
    __slots__ = ("ihave", "iwant", "graft", "prune")
    IHAVE_FIELD_NUMBER: _ClassVar[int]
    IWANT_FIELD_NUMBER: _ClassVar[int]
    GRAFT_FIELD_NUMBER: _ClassVar[int]
    PRUNE_FIELD_NUMBER: _ClassVar[int]
    ihave: _containers.RepeatedCompositeFieldContainer[ControlIHave]
    iwant: _containers.RepeatedCompositeFieldContainer[ControlIWant]
    graft: _containers.RepeatedCompositeFieldContainer[ControlGraft]
    prune: _containers.RepeatedCompositeFieldContainer[ControlPrune]
    def __init__(self, ihave: _Optional[_Iterable[_Union[ControlIHave, _Mapping]]] = ..., iwant: _Optional[_Iterable[_Union[ControlIWant, _Mapping]]] = ..., graft: _Optional[_Iterable[_Union[ControlGraft, _Mapping]]] = ..., prune: _Optional[_Iterable[_Union[ControlPrune, _Mapping]]] = ...) -> None: ... # type: ignore

class ControlIHave(_message.Message):
    __slots__ = ("topicID", "messageIDs")
    TOPICID_FIELD_NUMBER: _ClassVar[int]
    MESSAGEIDS_FIELD_NUMBER: _ClassVar[int]
    topicID: str
    messageIDs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, topicID: _Optional[str] = ..., messageIDs: _Optional[_Iterable[str]] = ...) -> None: ...

class ControlIWant(_message.Message):
    __slots__ = ("messageIDs",)
    MESSAGEIDS_FIELD_NUMBER: _ClassVar[int]
    messageIDs: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, messageIDs: _Optional[_Iterable[str]] = ...) -> None: ...

class ControlGraft(_message.Message):
    __slots__ = ("topicID",)
    TOPICID_FIELD_NUMBER: _ClassVar[int]
    topicID: str
    def __init__(self, topicID: _Optional[str] = ...) -> None: ...

class ControlPrune(_message.Message):
    __slots__ = ("topicID", "peers", "backoff")
    TOPICID_FIELD_NUMBER: _ClassVar[int]
    PEERS_FIELD_NUMBER: _ClassVar[int]
    BACKOFF_FIELD_NUMBER: _ClassVar[int]
    topicID: str
    peers: _containers.RepeatedCompositeFieldContainer[PeerInfo]
    backoff: int
    def __init__(self, topicID: _Optional[str] = ..., peers: _Optional[_Iterable[_Union[PeerInfo, _Mapping]]] = ..., backoff: _Optional[int] = ...) -> None: ...    # type: ignore

class PeerInfo(_message.Message):
    __slots__ = ("peerID", "signedPeerRecord")
    PEERID_FIELD_NUMBER: _ClassVar[int]
    SIGNEDPEERRECORD_FIELD_NUMBER: _ClassVar[int]
    peerID: bytes
    signedPeerRecord: bytes
    def __init__(self, peerID: _Optional[bytes] = ..., signedPeerRecord: _Optional[bytes] = ...) -> None: ...

class TopicDescriptor(_message.Message):
    __slots__ = ("name", "auth", "enc")
    class AuthOpts(_message.Message):
        __slots__ = ("mode", "keys")
        class AuthMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            NONE: _ClassVar[TopicDescriptor.AuthOpts.AuthMode]
            KEY: _ClassVar[TopicDescriptor.AuthOpts.AuthMode]
            WOT: _ClassVar[TopicDescriptor.AuthOpts.AuthMode]
        NONE: TopicDescriptor.AuthOpts.AuthMode
        KEY: TopicDescriptor.AuthOpts.AuthMode
        WOT: TopicDescriptor.AuthOpts.AuthMode
        MODE_FIELD_NUMBER: _ClassVar[int]
        KEYS_FIELD_NUMBER: _ClassVar[int]
        mode: TopicDescriptor.AuthOpts.AuthMode
        keys: _containers.RepeatedScalarFieldContainer[bytes]
        def __init__(self, mode: _Optional[_Union[TopicDescriptor.AuthOpts.AuthMode, str]] = ..., keys: _Optional[_Iterable[bytes]] = ...) -> None: ...
    class EncOpts(_message.Message):
        __slots__ = ("mode", "keyHashes")
        class EncMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = ()
            NONE: _ClassVar[TopicDescriptor.EncOpts.EncMode]
            SHAREDKEY: _ClassVar[TopicDescriptor.EncOpts.EncMode]
            WOT: _ClassVar[TopicDescriptor.EncOpts.EncMode]
        NONE: TopicDescriptor.EncOpts.EncMode
        SHAREDKEY: TopicDescriptor.EncOpts.EncMode
        WOT: TopicDescriptor.EncOpts.EncMode
        MODE_FIELD_NUMBER: _ClassVar[int]
        KEYHASHES_FIELD_NUMBER: _ClassVar[int]
        mode: TopicDescriptor.EncOpts.EncMode
        keyHashes: _containers.RepeatedScalarFieldContainer[bytes]
        def __init__(self, mode: _Optional[_Union[TopicDescriptor.EncOpts.EncMode, str]] = ..., keyHashes: _Optional[_Iterable[bytes]] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    AUTH_FIELD_NUMBER: _ClassVar[int]
    ENC_FIELD_NUMBER: _ClassVar[int]
    name: str
    auth: TopicDescriptor.AuthOpts
    enc: TopicDescriptor.EncOpts
    def __init__(self, name: _Optional[str] = ..., auth: _Optional[_Union[TopicDescriptor.AuthOpts, _Mapping]] = ..., enc: _Optional[_Union[TopicDescriptor.EncOpts, _Mapping]] = ...) -> None: ... # type: ignore

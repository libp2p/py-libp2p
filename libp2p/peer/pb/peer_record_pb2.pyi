from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PeerRecord(_message.Message):
    __slots__ = ("peer_id", "seq", "addresses")
    class AddressInfo(_message.Message):
        __slots__ = ("multiaddr",)
        MULTIADDR_FIELD_NUMBER: _ClassVar[int]
        multiaddr: bytes
        def __init__(self, multiaddr: _Optional[bytes] = ...) -> None: ...
    PEER_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    ADDRESSES_FIELD_NUMBER: _ClassVar[int]
    peer_id: bytes
    seq: int
    addresses: _containers.RepeatedCompositeFieldContainer[PeerRecord.AddressInfo]
    def __init__(self, peer_id: _Optional[bytes] = ..., seq: _Optional[int] = ..., addresses: _Optional[_Iterable[_Union[PeerRecord.AddressInfo, _Mapping]]] = ...) -> None: ...    # type: ignore[type-arg]

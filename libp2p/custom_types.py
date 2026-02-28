from collections.abc import (
    Awaitable,
    Callable,
    Mapping,
)
from typing import TYPE_CHECKING, NewType, Union, cast

from libp2p.transport.quic.stream import QUICStream

if TYPE_CHECKING:
    from libp2p.abc import IMuxedConn, IMuxedStream, INetStream, ISecureTransport
    from libp2p.transport.quic.connection import QUICConnection
else:
    IMuxedConn = cast(type, object)
    INetStream = cast(type, object)
    ISecureTransport = cast(type, object)
    IMuxedStream = cast(type, object)
    QUICConnection = cast(type, object)

from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.pubsub.pb import (
    rpc_pb2,
)

TProtocol = NewType("TProtocol", str)
MetadataValue = str | int | float | bool | None
StreamHandlerFn = Callable[[INetStream], Awaitable[None]]
THandler = Callable[[ReadWriteCloser], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, ISecureTransport]
TMuxerClass = type[IMuxedConn]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]
SyncValidatorFn = Callable[[ID, rpc_pb2.Message], bool]
AsyncValidatorFn = Callable[[ID, rpc_pb2.Message], Awaitable[bool]]
ValidatorFn = Union[SyncValidatorFn, AsyncValidatorFn]
UnsubscribeFn = Callable[[], Awaitable[None]]
TQUICStreamHandlerFn = Callable[[QUICStream], Awaitable[None]]
TQUICConnHandlerFn = Callable[[QUICConnection], Awaitable[None]]
MessageID = NewType("MessageID", str)

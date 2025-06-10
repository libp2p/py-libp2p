from collections.abc import (
    Awaitable,
    Callable,
    Mapping,
)
from typing import TYPE_CHECKING, NewType, Union, cast

if TYPE_CHECKING:
    from libp2p.abc import (
        IMuxedConn,
        INetStream,
        ISecureTransport,
    )
else:
    IMuxedConn = cast(type, object)
    INetStream = cast(type, object)
    ISecureTransport = cast(type, object)


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
StreamHandlerFn = Callable[[INetStream], Awaitable[None]]
THandler = Callable[[ReadWriteCloser], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, ISecureTransport]
TMuxerClass = type[IMuxedConn]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]
SyncValidatorFn = Callable[[ID, rpc_pb2.Message], bool]
AsyncValidatorFn = Callable[[ID, rpc_pb2.Message], Awaitable[bool]]
ValidatorFn = Union[SyncValidatorFn, AsyncValidatorFn]
UnsubscribeFn = Callable[[], Awaitable[None]]

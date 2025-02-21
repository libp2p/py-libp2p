from collections.abc import (
    Awaitable,
    Mapping,
)
from typing import (
    TYPE_CHECKING,
    Callable,
    NewType,
    Union,
)

if TYPE_CHECKING:
    from libp2p.abc import (
        IMuxedConn,
        INetStream,
        ISecureTransport,
    )
else:

    class INetStream:
        pass

    class IMuxedConn:
        pass

    class ISecureTransport:
        pass


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
StreamHandlerFn = Callable[["INetStream"], Awaitable[None]]
THandler = Callable[[ReadWriteCloser], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, "ISecureTransport"]
TMuxerClass = type["IMuxedConn"]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]
SyncValidatorFn = Callable[[ID, rpc_pb2.Message], bool]
AsyncValidatorFn = Callable[[ID, rpc_pb2.Message], Awaitable[bool]]
ValidatorFn = Union[SyncValidatorFn, AsyncValidatorFn]
UnsubscribeFn = Callable[[], Awaitable[None]]

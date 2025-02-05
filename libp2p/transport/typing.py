from collections.abc import (
    Awaitable,
    Mapping,
)
from typing import (
    TYPE_CHECKING,
    Callable,
)

if TYPE_CHECKING:
    from libp2p.abc import (
        IMuxedConn,
        ISecureTransport,
        ReadWriteCloser,
    )

from libp2p.custom_types import (
    TProtocol,
)

THandler = Callable[[ReadWriteCloser], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, ISecureTransport]
TMuxerClass = type[IMuxedConn]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]

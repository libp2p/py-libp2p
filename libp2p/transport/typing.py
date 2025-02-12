from collections.abc import (
    Awaitable,
    Mapping,
)
from typing import (
    Callable,
)

from libp2p.abc import (
    IMuxedConn,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.security.secure_transport_interface import (
    ISecureTransport,
)

THandler = Callable[[ReadWriteCloser], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, ISecureTransport]
TMuxerClass = type[IMuxedConn]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]

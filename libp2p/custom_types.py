from collections.abc import (
    Awaitable,
)
from typing import (
    TYPE_CHECKING,
    Callable,
    NewType,
)

if TYPE_CHECKING:
    from libp2p.abc import IMuxedStream  # noqa: F401
    from libp2p.abc import INetStream  # noqa: F401

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[["INetStream"], Awaitable[None]]

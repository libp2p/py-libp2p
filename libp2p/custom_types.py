from collections.abc import (
    Awaitable,
)
from typing import (
    TYPE_CHECKING,
    Callable,
    NewType,
)

if TYPE_CHECKING:
    from libp2p.abc import (  # noqa: F401
        IMuxedStream,
        INetStream,
    )

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[["INetStream"], Awaitable[None]]

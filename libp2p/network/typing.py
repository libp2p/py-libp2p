from typing import Awaitable, Callable

from libp2p.stream_muxer.abc import IMuxedStream

GenericProtocolHandlerFn = Callable[[IMuxedStream], Awaitable[None]]

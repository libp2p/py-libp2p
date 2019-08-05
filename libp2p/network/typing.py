from typing import Awaitable, Callable
from libp2p.stream_muxer.muxed_stream_interface import IMuxedStream

GenericProtocolHandlerFn = Callable[[IMuxedStream], Awaitable[None]]

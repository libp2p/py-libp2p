from typing import Awaitable, Callable, NewType

from libp2p.network.stream.net_stream_interface import INetStream

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[[INetStream], Awaitable[None]]

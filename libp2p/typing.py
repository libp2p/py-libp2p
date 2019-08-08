from typing import Awaitable, Callable, NewType, Union

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.stream_muxer.abc import IMuxedStream

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[[INetStream], Awaitable[None]]


NegotiableTransport = Union[IMuxedStream, IRawConnection]

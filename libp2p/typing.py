from typing import TYPE_CHECKING, Awaitable, Callable, NewType, Union

from libp2p.network.connection.raw_connection_interface import IRawConnection

if TYPE_CHECKING:
    from libp2p.network.stream.net_stream_interface import INetStream  # noqa: F401
    from libp2p.stream_muxer.abc import IMuxedStream  # noqa: F401

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[["INetStream"], Awaitable[None]]


StreamReader = Union["IMuxedStream", IRawConnection]

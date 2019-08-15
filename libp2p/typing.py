import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable, NewType, Union

if TYPE_CHECKING:
    from libp2p.network.stream.net_stream_interface import INetStream  # noqa: F401
    from libp2p.stream_muxer.abc import IMuxedStream  # noqa: F401

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[["INetStream"], Awaitable[None]]


StreamReader = Union["IMuxedStream", asyncio.StreamReader]

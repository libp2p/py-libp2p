from asyncio import StreamReader, StreamWriter
from typing import Awaitable, Callable, Mapping, Type

from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.typing import TProtocol

THandler = Callable[[StreamReader, StreamWriter], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, ISecureTransport]
TMuxerClass = Type[IMuxedConn]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]

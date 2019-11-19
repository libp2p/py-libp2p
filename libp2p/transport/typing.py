from typing import Awaitable, Callable, Mapping, Type

from libp2p.io.abc import ReadWriteCloser
from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.typing import TProtocol

THandler = Callable[[ReadWriteCloser], Awaitable[None]]
TSecurityOptions = Mapping[TProtocol, ISecureTransport]
TMuxerClass = Type[IMuxedConn]
TMuxerOptions = Mapping[TProtocol, TMuxerClass]

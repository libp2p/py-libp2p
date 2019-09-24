from abc import abstractmethod
from typing import Tuple

from libp2p.io.abc import Closer
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.stream_muxer.abc import IMuxedConn


class INetConn(Closer):
    muxed_conn: IMuxedConn

    @abstractmethod
    async def new_stream(self) -> INetStream:
        ...

    @abstractmethod
    async def get_streams(self) -> Tuple[INetStream, ...]:
        ...

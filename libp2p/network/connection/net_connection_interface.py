from abc import abstractmethod
from typing import Tuple

import trio

from libp2p.io.abc import Closer
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.stream_muxer.abc import IMuxedConn


class INetConn(Closer):
    muxed_conn: IMuxedConn
    event_started: trio.Event

    @abstractmethod
    async def new_stream(self) -> INetStream:
        ...

    @abstractmethod
    def get_streams(self) -> Tuple[INetStream, ...]:
        ...

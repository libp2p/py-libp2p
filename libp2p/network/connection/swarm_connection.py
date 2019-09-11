import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, List, Set, Tuple

from libp2p.network.connection.net_connection_interface import INetConn
from libp2p.network.stream.net_stream import NetStream
from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm  # noqa: F401


"""
Reference: https://github.com/libp2p/go-libp2p-swarm/blob/04c86bbdafd390651cb2ee14e334f7caeedad722/swarm_conn.go  # noqa: E501
"""


class SwarmConn(INetConn):
    conn: IMuxedConn
    swarm: "Swarm"
    streams: Set[NetStream]
    event_closed: asyncio.Event

    _tasks: List["asyncio.Future[Any]"]

    def __init__(self, conn: IMuxedConn, swarm: "Swarm") -> None:
        self.conn = conn
        self.swarm = swarm
        self.streams = set()
        self.event_closed = asyncio.Event()

        self._tasks = []

    async def close(self) -> None:
        if self.event_closed.is_set():
            return
        self.event_closed.set()
        await self.conn.close()
        for task in self._tasks:
            task.cancel()

        # TODO: Reset streams for local.
        # TODO: Notify closed.

    async def _handle_new_streams(self) -> None:
        while True:
            print("!@# SwarmConn._handle_new_streams")
            stream = await self.conn.accept_stream()
            print("!@# SwarmConn._handle_new_streams: accept_stream:", stream)
            net_stream = await self._add_stream(stream)
            print("!@# SwarmConn.calling swarm_stream_handler")
            await self.run_task(self.swarm.swarm_stream_handler(net_stream))
        await self.close()

    async def _add_stream(self, muxed_stream: IMuxedStream) -> NetStream:
        print("!@# SwarmConn._add_stream:", muxed_stream)
        net_stream = NetStream(muxed_stream)
        # Call notifiers since event occurred
        for notifee in self.swarm.notifees:
            await notifee.opened_stream(self.swarm, net_stream)
        return net_stream

    async def start(self) -> None:
        print("!@# SwarmConn.start")
        await self.run_task(self._handle_new_streams())

    async def run_task(self, coro: Awaitable[Any]) -> None:
        self._tasks.append(asyncio.ensure_future(coro))

    async def new_stream(self) -> NetStream:
        muxed_stream = await self.conn.open_stream()
        return await self._add_stream(muxed_stream)

    async def get_streams(self) -> Tuple[NetStream, ...]:
        return tuple(self.streams)

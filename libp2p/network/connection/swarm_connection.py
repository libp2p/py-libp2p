import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, List, Set, Tuple

from libp2p.network.connection.net_connection_interface import INetConn
from libp2p.network.stream.net_stream import NetStream
from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream
from libp2p.stream_muxer.exceptions import MuxedConnUnavailable

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm  # noqa: F401


"""
Reference: https://github.com/libp2p/go-libp2p-swarm/blob/04c86bbdafd390651cb2ee14e334f7caeedad722/swarm_conn.go  # noqa: E501
"""


class SwarmConn(INetConn):
    muxed_conn: IMuxedConn
    swarm: "Swarm"
    streams: Set[NetStream]
    event_closed: asyncio.Event

    _tasks: List["asyncio.Future[Any]"]

    def __init__(self, muxed_conn: IMuxedConn, swarm: "Swarm") -> None:
        self.muxed_conn = muxed_conn
        self.swarm = swarm
        self.streams = set()
        self.event_closed = asyncio.Event()

        self._tasks = []

    async def close(self) -> None:
        if self.event_closed.is_set():
            return
        self.event_closed.set()
        self.swarm.remove_conn(self)

        await self.muxed_conn.close()

        # This is just for cleaning up state. The connection has already been closed.
        # We *could* optimize this but it really isn't worth it.
        for stream in self.streams:
            await stream.reset()
        # Force context switch for stream handlers to process the stream reset event we just emit
        # before we cancel the stream handler tasks.
        await asyncio.sleep(0.1)

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Schedule `self._notify_disconnected` to make it execute after `close` is finished.
        self._notify_disconnected()

    async def _handle_new_streams(self) -> None:
        while True:
            try:
                stream = await self.muxed_conn.accept_stream()
            except MuxedConnUnavailable:
                # If there is anything wrong in the MuxedConn,
                # we should break the loop and close the connection.
                break
            # Asynchronously handle the accepted stream, to avoid blocking the next stream.
            await self.run_task(self._handle_muxed_stream(stream))

        await self.close()

    async def _call_stream_handler(self, net_stream: NetStream) -> None:
        try:
            await self.swarm.common_stream_handler(net_stream)
        # TODO: More exact exceptions
        except Exception:
            # TODO: Emit logs.
            # TODO: Clean up and remove the stream from SwarmConn if there is anything wrong.
            self.remove_stream(net_stream)

    async def _handle_muxed_stream(self, muxed_stream: IMuxedStream) -> None:
        net_stream = self._add_stream(muxed_stream)
        if self.swarm.common_stream_handler is not None:
            await self.run_task(self._call_stream_handler(net_stream))

    def _add_stream(self, muxed_stream: IMuxedStream) -> NetStream:
        net_stream = NetStream(muxed_stream)
        self.streams.add(net_stream)
        self.swarm.notify_opened_stream(net_stream)
        return net_stream

    def _notify_disconnected(self) -> None:
        self.swarm.notify_disconnected(self)

    async def start(self) -> None:
        await self.run_task(self._handle_new_streams())

    async def run_task(self, coro: Awaitable[Any]) -> None:
        self._tasks.append(asyncio.ensure_future(coro))

    async def new_stream(self) -> NetStream:
        muxed_stream = await self.muxed_conn.open_stream()
        return self._add_stream(muxed_stream)

    async def get_streams(self) -> Tuple[NetStream, ...]:
        return tuple(self.streams)

    def remove_stream(self, stream: NetStream) -> None:
        if stream not in self.streams:
            return
        self.streams.remove(stream)

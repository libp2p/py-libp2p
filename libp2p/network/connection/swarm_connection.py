import logging
from typing import (
    TYPE_CHECKING,
)

import trio

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
    INetConn,
)
from libp2p.network.stream.net_stream import (
    NetStream,
)
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
)

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm  # noqa: F401


"""
Reference: https://github.com/libp2p/go-libp2p-swarm/blob/04c86bbdafd390651cb2ee14e334f7caeedad722/swarm_conn.go
"""


class SwarmConn(INetConn):
    muxed_conn: IMuxedConn
    swarm: "Swarm"
    streams: set[NetStream]
    event_closed: trio.Event

    def __init__(
        self,
        muxed_conn: IMuxedConn,
        swarm: "Swarm",
    ) -> None:
        self.muxed_conn = muxed_conn
        self.swarm = swarm
        self.streams = set()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()
        if hasattr(muxed_conn, "on_close"):
            logging.debug(f"Setting on_close for peer {muxed_conn.peer_id}")
            setattr(muxed_conn, "on_close", self._on_muxed_conn_closed)
        else:
            logging.error(
                f"muxed_conn for peer {muxed_conn.peer_id} has no on_close attribute"
            )

    @property
    def is_closed(self) -> bool:
        return self.event_closed.is_set()

    async def _on_muxed_conn_closed(self) -> None:
        """Handle closure of the underlying muxed connection."""
        peer_id = self.muxed_conn.peer_id
        logging.debug(f"SwarmConn closing for peer {peer_id} due to muxed_conn closure")
        # Only call close if we're not already closing
        if not self.event_closed.is_set():
            await self.close()

    async def close(self) -> None:
        if self.event_closed.is_set():
            return
        logging.debug(f"Closing SwarmConn for peer {self.muxed_conn.peer_id}")
        self.event_closed.set()

        # Close the muxed connection
        try:
            await self.muxed_conn.close()
        except Exception as e:
            logging.warning(f"Error while closing muxed connection: {e}")

        # Perform proper cleanup of resources
        await self._cleanup()

    async def _cleanup(self) -> None:
        # Remove the connection from swarm
        logging.debug(f"Removing connection for peer {self.muxed_conn.peer_id}")
        self.swarm.remove_conn(self)

        # Only close the connection if it's not already closed
        # Be defensive here to avoid exceptions during cleanup
        try:
            if not self.muxed_conn.is_closed:
                await self.muxed_conn.close()
        except Exception as e:
            logging.warning(f"Error closing muxed connection: {e}")

        # This is just for cleaning up state. The connection has already been closed.
        # We *could* optimize this but it really isn't worth it.
        logging.debug(f"Resetting streams for peer {self.muxed_conn.peer_id}")
        for stream in self.streams.copy():
            try:
                await stream.reset()
            except Exception as e:
                logging.warning(f"Error resetting stream: {e}")

        # Force context switch for stream handlers to process the stream reset event we
        # just emit before we cancel the stream handler tasks.
        await trio.sleep(0.1)

        # Notify all listeners about the disconnection
        logging.debug(f"Notifying disconnection for peer {self.muxed_conn.peer_id}")
        await self._notify_disconnected()

    async def _handle_new_streams(self) -> None:
        self.event_started.set()
        async with trio.open_nursery() as nursery:
            while True:
                try:
                    stream = await self.muxed_conn.accept_stream()
                except MuxedConnUnavailable:
                    await self.close()
                    break
                # Asynchronously handle the accepted stream, to avoid blocking
                # the next stream.
                nursery.start_soon(self._handle_muxed_stream, stream)

    async def _handle_muxed_stream(self, muxed_stream: IMuxedStream) -> None:
        net_stream = await self._add_stream(muxed_stream)
        try:
            await self.swarm.common_stream_handler(net_stream)
        finally:
            # As long as `common_stream_handler`, remove the stream.
            self.remove_stream(net_stream)

    async def _add_stream(self, muxed_stream: IMuxedStream) -> NetStream:
        net_stream = NetStream(muxed_stream)
        self.streams.add(net_stream)
        await self.swarm.notify_opened_stream(net_stream)
        return net_stream

    async def _notify_disconnected(self) -> None:
        await self.swarm.notify_disconnected(self)

    async def start(self) -> None:
        await self._handle_new_streams()

    async def new_stream(self) -> NetStream:
        muxed_stream = await self.muxed_conn.open_stream()
        return await self._add_stream(muxed_stream)

    def get_streams(self) -> tuple[NetStream, ...]:
        return tuple(self.streams)

    def remove_stream(self, stream: NetStream) -> None:
        if stream not in self.streams:
            return
        self.streams.remove(stream)

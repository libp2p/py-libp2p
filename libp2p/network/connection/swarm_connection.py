import logging
from typing import (
    TYPE_CHECKING,
    Any,
)

from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
    INetConn,
)
from libp2p.network.stream.net_stream import (
    NetStream,
    StreamState,
)
from libp2p.rcmgr import Direction
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
)

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm  # noqa: F401


"""
Reference: https://github.com/libp2p/go-libp2p-swarm/blob/
04c86bbdafd390651cb2ee14e334f7caeedad722/swarm_conn.go
"""


class SwarmConn(INetConn):
    muxed_conn: IMuxedConn
    swarm: "Swarm"
    streams: set[NetStream]
    event_closed: trio.Event
    _resource_scope: Any | None

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
        self._resource_scope = None
        # Provide back-references/hooks expected by NetStream
        try:
            setattr(self.muxed_conn, "swarm", self.swarm)

            # NetStream expects an awaitable remove_stream hook
            async def _remove_stream_hook(stream: NetStream) -> None:
                self.remove_stream(stream)

            setattr(self.muxed_conn, "remove_stream", _remove_stream_hook)
        except Exception as e:
            logging.warning(
                f"Failed to set optional conveniences on muxed_conn "
                f"for peer {muxed_conn.peer_id}: {e}"
            )
            # optional conveniences
        if hasattr(muxed_conn, "on_close"):
            logging.debug(f"Setting on_close for peer {muxed_conn.peer_id}")
            setattr(muxed_conn, "on_close", self._on_muxed_conn_closed)
        else:
            logging.error(
                f"muxed_conn for peer {muxed_conn.peer_id} has no on_close attribute"
            )

    def set_resource_scope(self, scope: Any) -> None:
        """Set the resource scope for this connection."""
        self._resource_scope = scope

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

        # Clean up resource scope if it exists
        if self._resource_scope is not None:
            try:
                # Release the resource scope
                if hasattr(self._resource_scope, "close"):
                    await self._resource_scope.close()
                elif hasattr(self._resource_scope, "release"):
                    self._resource_scope.release()
                logging.debug(
                    f"Released resource scope for peer {self.muxed_conn.peer_id}"
                )
            except Exception as e:
                logging.warning(f"Error releasing resource scope: {e}")
            finally:
                self._resource_scope = None

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
        # Acquire inbound stream resource if a manager is configured
        rm = getattr(self.swarm, "_resource_manager", None)
        peer_id_str = str(getattr(self.muxed_conn, "peer_id", ""))
        acquired = False
        if rm is not None:
            try:
                acquired = rm.acquire_stream(peer_id_str, Direction.INBOUND)
            except Exception:
                acquired = False

        if rm is not None and not acquired:
            # Deny stream: best-effort reset/close
            try:
                await muxed_stream.reset()  # type: ignore[attr-defined]
            except Exception:
                try:
                    await muxed_stream.close()
                except Exception:
                    pass
            return

        net_stream = await self._add_stream(muxed_stream)
        try:
            await self.swarm.common_stream_handler(net_stream)
        finally:
            # Always remove the stream when the handler finishes
            # Use simple remove_stream since stream handles notifications itself
            self.remove_stream(net_stream)
            # Release inbound stream resource
            if rm is not None and acquired:
                try:
                    rm.release_stream(peer_id_str, Direction.INBOUND)
                except Exception:
                    pass

    async def _add_stream(self, muxed_stream: IMuxedStream) -> NetStream:
        #
        net_stream = NetStream(muxed_stream, self)
        # Set Stream state to OPEN if the event has already started.
        # This is to ensure that the new streams created after connection has started
        # are immediately set to OPEN state.
        if self.event_started.is_set():
            await net_stream.set_state(StreamState.OPEN)
        self.streams.add(net_stream)
        await self.swarm.notify_opened_stream(net_stream)
        return net_stream

    async def _notify_disconnected(self) -> None:
        await self.swarm.notify_disconnected(self)

    async def start(self) -> None:
        streams_open = self.get_streams()
        for stream in streams_open:
            """Set the state of the stream to OPEN."""
            await stream.set_state(StreamState.OPEN)
        await self._handle_new_streams()

    async def new_stream(self) -> NetStream:
        muxed_stream = await self.muxed_conn.open_stream()
        return await self._add_stream(muxed_stream)

    def get_streams(self) -> tuple[NetStream, ...]:
        return tuple(self.streams)

    def get_transport_addresses(self) -> list[Multiaddr]:
        """
        Retrieve the transport addresses used by this connection.

        Returns
        -------
        list[Multiaddr]
            A list of multiaddresses used by the transport.

        """
        # Return the addresses from the peerstore for this peer
        try:
            peer_id = self.muxed_conn.peer_id
            return self.swarm.peerstore.addrs(peer_id)
        except Exception as e:
            logging.warning(f"Error getting transport addresses: {e}")
            return []

    def remove_stream(self, stream: NetStream) -> None:
        if stream not in self.streams:
            return
        self.streams.remove(stream)

    async def _remove_stream(self, stream: NetStream) -> None:
        """Remove stream and notify about closure."""
        if stream not in self.streams:
            return
        self.streams.remove(stream)
        await self.swarm.notify_closed_stream(stream)

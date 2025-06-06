from enum import (
    Enum,
)
from typing import (
    Optional,
)

import trio

from libp2p.abc import (
    IMuxedStream,
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamError,
    MuxedStreamReset,
)

from .exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)


class StreamState(Enum):
    """NetStream States"""

    OPEN = "open"
    CLOSE_READ = "close_read"
    CLOSE_WRITE = "close_write"
    CLOSE_BOTH = "close_both"
    RESET = "reset"


class NetStream(INetStream):
    """Class representing NetStream Handler"""

    muxed_stream: IMuxedStream
    protocol_id: Optional[TProtocol]
    __stream_state: StreamState

    def __init__(
        self, muxed_stream: IMuxedStream, nursery: Optional[trio.Nursery] = None
    ) -> None:
        super().__init__()

        self.muxed_stream = muxed_stream
        self.muxed_conn = muxed_stream.muxed_conn
        self.protocol_id = None

        # For background tasks
        self._nursery = nursery

        # State management
        self.__stream_state = StreamState.OPEN
        self._state_lock = trio.Lock()

        # For notification handling
        self._notify_lock = trio.Lock()

    def get_protocol(self) -> TProtocol | None:
        """
        :return: protocol id that stream runs on
        """
        return self.protocol_id

    def set_protocol(self, protocol_id: TProtocol) -> None:
        """
        :param protocol_id: protocol id that stream runs on
        """
        self.protocol_id = protocol_id

    @property
    async def state(self) -> StreamState:
        """Get current stream state."""
        async with self._state_lock:
            return self.__stream_state

    async def read(self, n: Optional[int] = None) -> bytes:
        """
        Read from stream.

        :param n: number of bytes to read
        :return: bytes of input
        """
        async with self._state_lock:
            if self.__stream_state in [
                StreamState.CLOSE_READ,
                StreamState.CLOSE_BOTH,
            ]:
                raise StreamClosed("Stream is closed for reading")

            if self.__stream_state == StreamState.RESET:
                raise StreamReset("Stream is reset, cannot be used to read")

        try:
            data = await self.muxed_stream.read(n)
            return data
        except MuxedStreamEOF as error:
            async with self._state_lock:
                if self.__stream_state == StreamState.CLOSE_WRITE:
                    self.__stream_state = StreamState.CLOSE_BOTH
                    await self._remove()
                elif self.__stream_state == StreamState.OPEN:
                    self.__stream_state = StreamState.CLOSE_READ
            raise StreamEOF() from error
        except MuxedStreamReset as error:
            async with self._state_lock:
                if self.__stream_state in [
                    StreamState.OPEN,
                    StreamState.CLOSE_READ,
                    StreamState.CLOSE_WRITE,
                ]:
                    self.__stream_state = StreamState.RESET
                    await self._remove()
            raise StreamReset() from error

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :param data: bytes to write
        """
        async with self._state_lock:
            if self.__stream_state in [
                StreamState.CLOSE_WRITE,
                StreamState.CLOSE_BOTH,
                StreamState.RESET,
            ]:
                raise StreamClosed("Stream is closed for writing")

        try:
            await self.muxed_stream.write(data)
        except (MuxedStreamClosed, MuxedStreamError) as error:
            async with self._state_lock:
                if self.__stream_state == StreamState.OPEN:
                    self.__stream_state = StreamState.CLOSE_WRITE
                elif self.__stream_state == StreamState.CLOSE_READ:
                    self.__stream_state = StreamState.CLOSE_BOTH
                    await self._remove()
            raise StreamClosed() from error

    async def close(self) -> None:
        """Close stream for writing."""
        async with self._state_lock:
            if self.__stream_state in [
                StreamState.CLOSE_BOTH,
                StreamState.RESET,
                StreamState.CLOSE_WRITE,
            ]:
                return

        await self.muxed_stream.close()

        async with self._state_lock:
            if self.__stream_state == StreamState.CLOSE_READ:
                self.__stream_state = StreamState.CLOSE_BOTH
                await self._remove()
            elif self.__stream_state == StreamState.OPEN:
                self.__stream_state = StreamState.CLOSE_WRITE

    async def reset(self) -> None:
        """Reset stream, closing both ends."""
        async with self._state_lock:
            if self.__stream_state == StreamState.RESET:
                return

        await self.muxed_stream.reset()

        async with self._state_lock:
            if self.__stream_state in [
                StreamState.OPEN,
                StreamState.CLOSE_READ,
                StreamState.CLOSE_WRITE,
            ]:
                self.__stream_state = StreamState.RESET
                await self._remove()

    async def _remove(self) -> None:
        """
        Remove stream from connection and notify listeners.
        This is called when the stream is fully closed or reset.
        """
        if hasattr(self.muxed_conn, "remove_stream"):
            remove_stream = getattr(self.muxed_conn, "remove_stream")
            await remove_stream(self)

        # Notify in background using Trio nursery if available
        if self._nursery:
            self._nursery.start_soon(self._notify_closed)
        else:
            await self._notify_closed()

    async def _notify_closed(self) -> None:
        """
        Notify all listeners that the stream has been closed.
        This runs in a separate task to avoid blocking the main flow.
        """
        async with self._notify_lock:
            if hasattr(self.muxed_conn, "swarm"):
                swarm = getattr(self.muxed_conn, "swarm")

                if hasattr(swarm, "notify_all"):
                    await swarm.notify_all(
                        lambda notifiee: notifiee.closed_stream(swarm, self)
                    )

                if hasattr(swarm, "refs") and hasattr(swarm.refs, "done"):
                    swarm.refs.done()

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        """Delegate to the underlying muxed stream."""
        return self.muxed_stream.get_remote_address()

    def is_closed(self) -> bool:
        """Check if stream is closed."""
        return self.__stream_state in [StreamState.CLOSE_BOTH, StreamState.RESET]

    def is_readable(self) -> bool:
        """Check if stream is readable."""
        return self.__stream_state not in [
            StreamState.CLOSE_READ,
            StreamState.CLOSE_BOTH,
            StreamState.RESET,
        ]

    def is_writable(self) -> bool:
        """Check if stream is writable."""
        return self.__stream_state not in [
            StreamState.CLOSE_WRITE,
            StreamState.CLOSE_BOTH,
            StreamState.RESET,
        ]

    def __str__(self) -> str:
        """String representation of the stream."""
        return f"<NetStream[{self.__stream_state.value}] protocol={self.protocol_id}>"

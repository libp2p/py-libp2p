from enum import (
    Enum,
    auto,
)
from typing import (
    TYPE_CHECKING,
)

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
    MuxedStreamReset,
)

if TYPE_CHECKING:
    from libp2p.network.connection.swarm_connection import SwarmConn


from .exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)


class StreamState(Enum):
    INIT = auto()
    OPEN = auto()
    CLOSE_READ = auto()
    CLOSE_WRITE = auto()
    CLOSE_BOTH = auto()
    RESET = auto()
    ERROR = auto()


class NetStream(INetStream):
    muxed_stream: IMuxedStream
    protocol_id: TProtocol | None

    def __init__(
        self, muxed_stream: IMuxedStream, swarm_conn: "SwarmConn | None"
    ) -> None:
        self.muxed_stream = muxed_stream
        self.muxed_conn = muxed_stream.muxed_conn
        self.protocol_id = None
        self._state = StreamState.INIT
        self.swarm_conn = swarm_conn

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
    def state(self) -> StreamState:
        """
        :return: current state of the stream
        """
        return self._state

    def set_state(self, state: StreamState) -> None:
        """
        Set the current state of the stream.

        :param state: new state of the stream
        """
        self._state = state

    async def read(self, n: int | None = None) -> bytes:
        """
        Read from stream.

        :param n: number of bytes to read
        :return: Bytes read from the stream
        """
        if self.state == StreamState.RESET:
            raise StreamReset("Cannot read from stream; stream is reset")
        elif self.state == StreamState.CLOSE_READ:
            raise StreamClosed("Cannot read from stream; closed for reading")
        # Note: Allow reading from CLOSE_BOTH state - there might still be buffered data

        try:
            return await self.muxed_stream.read(n)
        except MuxedStreamEOF as error:
            # Handle state transitions when EOF is encountered
            if self.state == StreamState.CLOSE_WRITE:
                self.set_state(StreamState.CLOSE_BOTH)
            elif self.state == StreamState.OPEN:
                self.set_state(StreamState.CLOSE_READ)
            raise StreamEOF() from error
        except MuxedStreamReset as error:
            raise StreamReset() from error

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :param data: bytes to write
        """
        try:
            if self.state == StreamState.RESET:
                raise StreamReset("Cannot write to stream; stream is reset")
            elif self.state in [StreamState.CLOSE_WRITE, StreamState.CLOSE_BOTH]:
                raise StreamClosed("Cannot write to stream; closed for writing")
            else:
                await self.muxed_stream.write(data)
        except MuxedStreamClosed as error:
            if self.state == StreamState.CLOSE_READ:
                self.set_state(StreamState.CLOSE_BOTH)
            elif self.state == StreamState.OPEN:
                self.set_state(StreamState.CLOSE_WRITE)
            raise StreamClosed() from error
        except MuxedStreamReset as error:
            self.set_state(StreamState.RESET)
            raise StreamReset() from error

    async def close(self) -> None:
        """Close stream completely and clean up resources."""
        await self.muxed_stream.close()
        self.set_state(StreamState.CLOSE_BOTH)
        await self.remove()

    async def close_read(self) -> None:
        """Close the stream for reading only."""
        if self.state == StreamState.OPEN:
            self.set_state(StreamState.CLOSE_READ)
        elif self.state == StreamState.CLOSE_WRITE:
            self.set_state(StreamState.CLOSE_BOTH)
            await self.remove()

    async def close_write(self) -> None:
        """Close the stream for writing only."""
        await self.muxed_stream.close()
        if self.state == StreamState.OPEN:
            self.set_state(StreamState.CLOSE_WRITE)
        elif self.state == StreamState.CLOSE_READ:
            self.set_state(StreamState.CLOSE_BOTH)
            await self.remove()

    async def reset(self) -> None:
        """Reset stream."""
        await self.muxed_stream.reset()
        self.set_state(StreamState.RESET)
        await self.remove()

    async def remove(self) -> None:
        """
        Remove the stream from the connection and notify swarm that stream was closed.
        """
        if self.swarm_conn is not None:
            self.swarm_conn.remove_stream(self)
            await self.swarm_conn.swarm.notify_closed_stream(self)

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying muxed stream."""
        return self.muxed_stream.get_remote_address()

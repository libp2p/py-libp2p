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
    CLOSED = auto()
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
        try:
            if self.state == StreamState.RESET:
                raise StreamReset("Cannot read from stream; stream is reset")
            elif self.state != StreamState.OPEN:
                raise StreamClosed("Cannot read from stream; not open")
            else:
                return await self.muxed_stream.read(n)
        except MuxedStreamEOF as error:
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
            elif self.state == StreamState.CLOSED:
                raise StreamClosed("Cannot write to stream; stream is closed")
            elif self.state != StreamState.OPEN:
                raise StreamClosed("Cannot write to stream; not open")
            else:
                await self.muxed_stream.write(data)
        except MuxedStreamClosed as error:
            # Only set state to CLOSED if it wasn't already set
            if self.state != StreamState.CLOSED:
                self.set_state(StreamState.CLOSED)
            raise StreamClosed() from error
        except MuxedStreamReset as error:
            # Only set state to RESET if it wasn't already set
            if self.state != StreamState.RESET:
                self.set_state(StreamState.RESET)
            raise StreamReset() from error

    async def close(self) -> None:
        """Close stream."""
        # Don't set state to CLOSED immediately - keep it OPEN for pending operations
        # Only set to CLOSED after the underlying stream is fully closed
        await self.muxed_stream.close()
        # Now it's safe to set the state to CLOSED
        self.set_state(StreamState.CLOSED)
        # Notify that the stream is closed
        await self.remove()

    async def reset(self) -> None:
        """Reset stream."""
        # Don't set state to RESET immediately - keep it OPEN for pending operations
        # Only set to RESET after the underlying stream is fully reset
        await self.muxed_stream.reset()
        # Now it's safe to set the state to RESET
        self.set_state(StreamState.RESET)
        # Notify that the stream is closed/reset
        await self.remove()

    async def remove(self) -> None:
        """
        Remove the stream from the connection and notify swarm that stream was closed.
        This method should only be called when the stream is no longer needed.
        """
        if self.swarm_conn is not None and self in self.swarm_conn.streams:
            self.swarm_conn.remove_stream(self)
            await self.swarm_conn.swarm.notify_closed_stream(self)

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying muxed stream."""
        return self.muxed_stream.get_remote_address()

from typing import (
    Optional,
)
import trio
from enum import IntEnum

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

from .exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)

# Define StreamState Enum
class StreamState(IntEnum):
    STREAM_OPEN = 0
    STREAM_CLOSE_READ = 1
    STREAM_CLOSE_WRITE = 2
    STREAM_CLOSE_BOTH = 3
    STREAM_RESET = 4

class NetStream(INetStream):
    muxed_stream: IMuxedStream
    protocol_id: Optional[TProtocol]

    def __init__(self, muxed_stream: IMuxedStream) -> None:
        self.muxed_stream = muxed_stream
        self.muxed_conn = muxed_stream.muxed_conn
        self.protocol_id = None
        self.state = StreamState.STREAM_OPEN
        self.state_lock = trio.Lock()

    def get_protocol(self) -> TProtocol:
        """
        :return: protocol id that stream runs on
        """
        return self.protocol_id

    def set_protocol(self, protocol_id: TProtocol) -> None:
        """
        :param protocol_id: protocol id that stream runs on
        """
        self.protocol_id = protocol_id

    async def read(self, n: int = None) -> bytes:
        """
        Read from stream.

        :param n: number of bytes to read
        :return: bytes of input
        """
        try:
            return await self.muxed_stream.read(n)
        except MuxedStreamEOF as error:
            raise StreamEOF() from error
        except MuxedStreamReset as error:
            raise StreamReset() from error

    async def write(self, data: bytes) -> None:
        """
        Write to stream.

        :return: number of bytes written
        """
        try:
            await self.muxed_stream.write(data)
        except MuxedStreamClosed as error:
            raise StreamClosed() from error

    async def close(self) -> None:
        """Close stream."""
        async with self.state_lock:
            if self.state == StreamState.STREAM_OPEN:
                self.state = StreamState.STREAM_CLOSE_WRITE
            elif self.state == StreamState.STREAM_CLOSE_READ:
                self.state = StreamState.STREAM_CLOSE_BOTH
                await self.remove()
        await self.muxed_stream.close()

    async def reset(self) -> None:
        async with self.state_lock:
            if self.state in (StreamState.STREAM_OPEN, StreamState.STREAM_CLOSE_READ, StreamState.STREAM_CLOSE_WRITE):
                self.state = StreamState.STREAM_RESET
                await self.remove()
        await self.muxed_stream.reset()

    async def remove(self) -> None:
        await self.muxed_conn.remove_stream(self)
        # Notify `ClosedStream` after `SwarmConn.remove_stream`
        async with self.swarm.notify_all_lock:
            await self.swarm.notify_all(lambda f: f.closed_stream(self.swarm, self))

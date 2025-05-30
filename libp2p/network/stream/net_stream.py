from enum import Enum,auto

from typing import (
    Optional,
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
    MuxedStreamError,
    MuxedStreamReset,
)

from .exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)


# TODO: Handle exceptions from `muxed_stream`
# TODO: Add stream state
#   - Reference: https://github.com/libp2p/go-libp2p-swarm/blob/99831444e78c8f23c9335c17d8f7c700ba25ca14/swarm_stream.go  # noqa: E501
class StreamState(Enum):
    INIT = auto()
    OPEN = auto()
    RESET = auto()
    CLOSED = auto()
    ERROR = auto()


class NetStream(INetStream):
    muxed_stream: IMuxedStream
    protocol_id: Optional[TProtocol]

    def __init__(self, muxed_stream: IMuxedStream) -> None:
        self.muxed_stream = muxed_stream
        self.muxed_conn = muxed_stream.muxed_conn
        self.protocol_id = None
        self._state = StreamState.INIT

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

    @property
    def get_state(self) -> StreamState:
        """
        :return: current state of the stream
        """
        return self._state

    @property
    def set_state(self, state: StreamState) -> None:
        """
        Set the current state of the stream.

        :param state: new state of the stream
        """
        self._state = state

    async def read(self, n: int = None) -> bytes:
        """
        Read from stream.

        :param n: number of bytes to read
        :return: bytes of input
        """
        try:
            if self.get_state != StreamState.OPEN:
                self.set_state(StreamState.CLOSED)
                raise StreamClosed("Stream is closed, cannot read data.")
            else:
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
            if self.get_state != StreamState.OPEN:
                self.set_state(StreamState.CLOSED)
                raise StreamClosed("Stream is closed, cannot write data.")
            else:
                await self.muxed_stream.write(data)
        except (MuxedStreamClosed, MuxedStreamError) as error:
            self.set_state(StreamState.ERROR)
            raise StreamClosed() from error

    async def close(self) -> None:
        """Close stream."""
        self.set_state(StreamState.CLOSED)
        await self.muxed_stream.close()

    async def reset(self) -> None:
        self.set_state(StreamState.RESET)
        await self.muxed_stream.reset()

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        """Delegate to the underlying muxed stream."""
        return self.muxed_stream.get_remote_address()

    # TODO: `remove`: Called by close and write when the stream is in specific states.
    #   It notifies `ClosedStream` after `SwarmConn.remove_stream` is called.
    # Reference: https://github.com/libp2p/go-libp2p-swarm/blob/99831444e78c8f23c9335c17d8f7c700ba25ca14/swarm_stream.go  # noqa: E501

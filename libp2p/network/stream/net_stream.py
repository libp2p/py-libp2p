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
class NetStream(INetStream):
    muxed_stream: IMuxedStream
    protocol_id: Optional[TProtocol]

    def __init__(self, muxed_stream: IMuxedStream) -> None:
        self.muxed_stream = muxed_stream
        self.muxed_conn = muxed_stream.muxed_conn
        self.protocol_id = None

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
        await self.muxed_stream.close()

    async def reset(self) -> None:
        await self.muxed_stream.reset()

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        """Delegate to the underlying muxed stream."""
        return self.muxed_stream.get_remote_address()

    # TODO: `remove`: Called by close and write when the stream is in specific states.
    #   It notifies `ClosedStream` after `SwarmConn.remove_stream` is called.
    # Reference: https://github.com/libp2p/go-libp2p-swarm/blob/99831444e78c8f23c9335c17d8f7c700ba25ca14/swarm_stream.go  # noqa: E501

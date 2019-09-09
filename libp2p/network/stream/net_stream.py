from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream
from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamEOF,
    MuxedStreamReset,
)
from libp2p.typing import TProtocol

from .exceptions import StreamClosed, StreamEOF, StreamReset
from .net_stream_interface import INetStream


# TODO: Handle exceptions from `muxed_stream`
# TODO: Add stream state
#   - Reference: https://github.com/libp2p/go-libp2p-swarm/blob/99831444e78c8f23c9335c17d8f7c700ba25ca14/swarm_stream.go  # noqa: E501
class NetStream(INetStream):

    muxed_stream: IMuxedStream
    # TODO: Why we expose `mplex_conn` here?
    mplex_conn: IMuxedConn
    protocol_id: TProtocol

    def __init__(self, muxed_stream: IMuxedStream) -> None:
        self.muxed_stream = muxed_stream
        self.mplex_conn = muxed_stream.mplex_conn
        self.protocol_id = None

    def get_protocol(self) -> TProtocol:
        """
        :return: protocol id that stream runs on
        """
        return self.protocol_id

    def set_protocol(self, protocol_id: TProtocol) -> None:
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """
        self.protocol_id = protocol_id

    async def read(self, n: int = -1) -> bytes:
        """
        reads from stream
        :param n: number of bytes to read
        :return: bytes of input
        """
        try:
            return await self.muxed_stream.read(n)
        except MuxedStreamEOF as error:
            raise StreamEOF from error
        except MuxedStreamReset as error:
            raise StreamReset from error

    async def write(self, data: bytes) -> int:
        """
        write to stream
        :return: number of bytes written
        """
        try:
            return await self.muxed_stream.write(data)
        except MuxedStreamClosed as error:
            raise StreamClosed from error

    async def close(self) -> None:
        """
        close stream
        :return: true if successful
        """
        await self.muxed_stream.close()

    async def reset(self) -> None:
        await self.muxed_stream.reset()

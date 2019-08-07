from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream
from libp2p.typing import TProtocol

from .net_stream_interface import INetStream


class NetStream(INetStream):

    muxed_stream: IMuxedStream
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
        return await self.muxed_stream.read(n)

    async def write(self, data: bytes) -> int:
        """
        write to stream
        :return: number of bytes written
        """
        return await self.muxed_stream.write(data)

    async def close(self) -> bool:
        """
        close stream
        :return: true if successful
        """
        await self.muxed_stream.close()
        return True

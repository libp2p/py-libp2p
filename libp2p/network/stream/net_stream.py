from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream

from .net_stream_interface import INetStream


class NetStream(INetStream):

    muxed_stream: MplexStream
    mplex_conn: Mplex
    protocol_id: str

    def __init__(self, muxed_stream: MplexStream) -> None:
        self.muxed_stream = muxed_stream
        self.mplex_conn = muxed_stream.mplex_conn
        self.protocol_id = None

    def get_protocol(self) -> str:
        """
        :return: protocol id that stream runs on
        """
        return self.protocol_id

    def set_protocol(self, protocol_id: str) -> None:
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """
        self.protocol_id = protocol_id

    async def read(self) -> bytes:
        """
        read from stream
        :return: bytes of input until EOF
        """
        return await self.muxed_stream.read()

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

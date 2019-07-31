from abc import ABC, abstractmethod

from libp2p.stream_muxer.muxed_connection_interface import IMuxedConn


class INetStream(ABC):

    mplex_conn: IMuxedConn

    @abstractmethod
    def get_protocol(self) -> str:
        """
        :return: protocol id that stream runs on
        """

    @abstractmethod
    def set_protocol(self, protocol_id: str) -> bool:
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """

    @abstractmethod
    async def read(self) -> bytes:
        """
        reads from the underlying muxed_stream
        :return: bytes of input
        """

    @abstractmethod
    async def write(self, data: bytes) -> int:
        """
        write to the underlying muxed_stream
        :return: number of bytes written
        """

    @abstractmethod
    async def close(self) -> bool:
        """
        close the underlying muxed stream
        :return: true if successful
        """

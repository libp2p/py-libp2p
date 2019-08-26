from abc import ABC, abstractmethod

from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.typing import TProtocol


class INetStream(ABC):

    mplex_conn: IMuxedConn

    @abstractmethod
    def get_protocol(self) -> TProtocol:
        """
        :return: protocol id that stream runs on
        """

    @abstractmethod
    def set_protocol(self, protocol_id: TProtocol) -> bool:
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """

    @abstractmethod
    async def read(self, n: int = -1) -> bytes:
        """
        reads from the underlying muxed_stream
        :param n: number of bytes to read
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

    @abstractmethod
    async def reset(self) -> bool:
        """
        Close both ends of the stream.
        """

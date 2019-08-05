from abc import ABC, abstractmethod
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from libp2p.stream_muxer.muxed_connection_interface import IMuxedConn


class IMuxedStream(ABC):

    mplex_conn: "IMuxedConn"

    @abstractmethod
    async def read(self) -> bytes:
        """
        reads from the underlying muxed_conn
        :return: bytes of input
        """

    @abstractmethod
    async def write(self, data: bytes) -> int:
        """
        writes to the underlying muxed_conn
        :return: number of bytes written
        """

    @abstractmethod
    async def close(self) -> bool:
        """
        close the underlying muxed_conn
        :return: true if successful
        """

    @abstractmethod
    async def reset(self) -> bool:
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: true if successful
        """

    @abstractmethod
    def set_deadline(self, ttl: float) -> bool:
        """
        set deadline for muxed stream
        :return: a new stream
        """

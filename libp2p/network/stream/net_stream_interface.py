from abc import abstractmethod

from libp2p.io.abc import ReadWriteCloser
from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.typing import TProtocol


class INetStream(ReadWriteCloser):

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
    async def reset(self) -> None:
        """
        Close both ends of the stream.
        """

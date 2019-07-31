from abc import (
    ABC,
    abstractmethod,
)
from typing import TYPE_CHECKING

from multiaddr import Multiaddr

from libp2p.stream_muxer.muxed_connection_interface import IMuxedConn

from libp2p.network.stream.net_stream_interface import INetStream

if TYPE_CHECKING:
    from .network_interface import INetwork


class INotifee(ABC):

    @abstractmethod
    async def opened_stream(self, network: 'INetwork', stream: INetStream) -> None:
        """
        :param network: network the stream was opened on
        :param stream: stream that was opened
        """

    @abstractmethod
    async def closed_stream(self, network: 'INetwork', stream: INetStream) -> None:
        """
        :param network: network the stream was closed on
        :param stream: stream that was closed
        """

    @abstractmethod
    async def connected(self, network: 'INetwork', conn: IMuxedConn) -> None:
        """
        :param network: network the connection was opened on
        :param conn: connection that was opened
        """

    @abstractmethod
    async def disconnected(self, network: 'INetwork', conn: IMuxedConn) -> None:
        """
        :param network: network the connection was closed on
        :param conn: connection that was closed
        """

    @abstractmethod
    async def listen(self, network: 'INetwork', multiaddr: Multiaddr) -> None:
        """
        :param network: network the listener is listening on
        :param multiaddr: multiaddress listener is listening on
        """

    @abstractmethod
    async def listen_close(self, network: 'INetwork', multiaddr: Multiaddr) -> None:
        """
        :param network: network the connection was opened on
        :param multiaddr: multiaddress listener is no longer listening on
        """

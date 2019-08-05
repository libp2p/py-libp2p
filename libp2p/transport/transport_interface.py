from abc import ABC, abstractmethod

from multiaddr import Multiaddr

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID

from .listener_interface import IListener
from .typing import THandler


class ITransport(ABC):
    @abstractmethod
    async def dial(self, maddr: Multiaddr, self_id: ID) -> IRawConnection:
        """
        dial a transport to peer listening on multiaddr
        :param multiaddr: multiaddr of peer
        :param self_id: peer_id of the dialer (to send to receiver)
        :return: list of multiaddrs
        """

    @abstractmethod
    def create_listener(self, handler_function: THandler) -> IListener:
        """
        create listener on transport
        :param handler_function: a function called when a new conntion is received
        that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """

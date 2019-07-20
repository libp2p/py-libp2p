from abc import ABC, abstractmethod


class ITransport(ABC):

    @abstractmethod
    def dial(self, maddr, self_id, options=None):
        """
        dial a transport to peer listening on multiaddr
        :param multiaddr: multiaddr of peer
        :param self_id: peer_id of the dialer (to send to receiver)
        :param options: optional object
        :return: list of multiaddrs
        """

    @abstractmethod
    def create_listener(self, handler_function, options=None):
        """
        create listener on transport
        :param options: optional object with properties the listener must have
        :param handler_function: a function called when a new conntion is received
        that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """

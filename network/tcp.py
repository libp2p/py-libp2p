import asyncio
from .transport_interface import ITransport
from .listener_interface import IListener

class TCP(ITransport):

    def __init__(self):
        self.multiaddr = None

    class Listener(IListener):

        def listen(self, multiaddr):
            """
            put listener in listening mode and wait for incoming connections
            :param multiaddr: multiaddr of peer
            :return: return True if successful
            """
            pass

        def get_addrs(self):
            """
            retrieve list of addresses the listener is listening on
            :return: return list of addrs
            """
            pass

        def close(self, options=None):
            """
            close the listener such that no more connections
            can be open on this transport instance
            :param options: optional object potential with timeout
            a timeout value in ms that fires and destroy all connections
            :return: return True if successful
            """
            pass

    def dial(self, multiaddr, options=None):
        """
        dial a transport to peer listening on multiaddr
        :param multiaddr: multiaddr of peer
        :param options: optional object
        :return: list of multiaddrs
        """
        pass

    def create_listener(self, handler_function, options=None):
        """
        create listener on transport
        :param options: optional object with properties the listener must have
        :param handler_function: a function called when a new conntion is received
        that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        pass

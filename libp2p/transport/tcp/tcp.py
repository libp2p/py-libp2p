import asyncio

import multiaddr

from libp2p.network.connection.raw_connection import RawConnection
from libp2p.peer.id import id_b58_encode

from ..listener_interface import IListener
from ..transport_interface import ITransport


class TCP(ITransport):

    def __init__(self):
        self.listener = self.Listener()

    class Listener(IListener):

        def __init__(self, handler_function=None):
            self.multiaddrs = []
            self.server = None
            self.handler = handler_function

        async def listen(self, multiaddr):
            """
            put listener in listening mode and wait for incoming connections
            :param multiaddr: multiaddr of peer
            :return: return True if successful
            """
            _multiaddr = multiaddr
            _multiaddr = _multiaddr.decapsulate('/p2p')

            coroutine = asyncio.start_server(self.handler,
                                             _multiaddr.value_for_protocol('ip4'),
                                             _multiaddr.value_for_protocol('tcp'))
            self.server = await coroutine
            socket = self.server.sockets[0]
            self.multiaddrs.append(_multiaddr_from_socket(socket))

            return True

        def get_addrs(self):
            """
            retrieve list of addresses the listener is listening on
            :return: return list of addrs
            """
            # TODO check if server is listening
            return self.multiaddrs

        def shutdown(self, options=None):
            """
            start the closing of the listener usefull for closing multiple
            connection at once.
            :param options: optional object potential with a timeout value
            in ms that fires and destroy all connections
            :return: return True if successful
            """
            if self.server is None:
                return False
            self.server.close()
            return True

        async def wait_closed(self):
            """
            Wait until the connection is closed. Usefull for closing multiple
            connection at once. Must be used after shutdown.
            For an all in one close use close.
            """
            await self.server.wait_close()

        def close(self, options=None):
            """
            close the listener such that no more connections
            can be open on this transport instance
            :param options: optional object potential with a timeout value
            in ms that fires and destroy all connections
            :return: return True if successful
            """
            if self.shutdown(options) is False:
                return False
            _loop = asyncio.get_event_loop()
            _loop.run_until_complete(self.wait_closed())
            _loop.close()
            self.server = None
            return True

    async def dial(self, multiaddr, self_id, options=None):
        """
        dial a transport to peer listening on multiaddr
        :param multiaddr: multiaddr of peer
        :param self_id: peer_id of the dialer (to send to receiver)
        :param options: optional object
        :return: True if successful
        """
        host = multiaddr.value_for_protocol('ip4')
        port = int(multiaddr.value_for_protocol('tcp'))

        reader, writer = await asyncio.open_connection(host, port)

        # First: send our peer ID so receiver knows it
        writer.write(id_b58_encode(self_id).encode())
        await writer.drain()

        # Await ack for peer id
        ack = (await reader.read(1024)).decode()

        if ack != "received peer id":
            raise Exception("Receiver did not receive peer id")

        return RawConnection(host, port, reader, writer, True)

    def create_listener(self, handler_function, options=None):
        """
        create listener on transport
        :param options: optional object with properties the listener must have
        :param handler_function: a function called when a new connection is received
        that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        return self.Listener(handler_function)


def _multiaddr_from_socket(socket):
    return multiaddr.Multiaddr("/ip4/%s/tcp/%s" % socket.getsockname())

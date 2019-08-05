import asyncio

from typing import List, Callable
from multiaddr import Multiaddr

from socket import socket
from libp2p.transport.typing import THandler
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.connection.raw_connection import RawConnection

from libp2p.transport.listener_interface import IListener
from libp2p.transport.transport_interface import ITransport


class TCPListener(IListener):
    multiaddrs: List[Multiaddr]
    server = None
    handler = None

    def __init__(self, handler_function: THandler = None) -> None:
        self.multiaddrs = []
        self.server = None
        self.handler = handler_function

    async def listen(self, maddr: Multiaddr) -> bool:
        """
        put listener in listening mode and wait for incoming connections
        :param maddr: maddr of peer
        :return: return True if successful
        """
        self.server = await asyncio.start_server(
            self.handler,
            maddr.value_for_protocol("ip4"),
            maddr.value_for_protocol("tcp"),
        )
        socket = self.server.sockets[0]
        self.multiaddrs.append(_multiaddr_from_socket(socket))

        return True

    def get_addrs(self) -> List[Multiaddr]:
        """
        retrieve list of addresses the listener is listening on
        :return: return list of addrs
        """
        # TODO check if server is listening
        return self.multiaddrs

    def close(self) -> bool:
        """
        close the listener such that no more connections
        can be open on this transport instance
        :return: return True if successful
        """
        if self.server is None:
            return False
        self.server.close()
        _loop = asyncio.get_event_loop()
        _loop.run_until_complete(self.server.wait_closed())
        _loop.close()
        self.server = None
        return True


class TCP(ITransport):
    def __init__(self) -> None:
        self.listener = TCPListener()

    async def dial(self, maddr: Multiaddr, self_id: ID) -> IRawConnection:
        """
        dial a transport to peer listening on multiaddr
        :param maddr: multiaddr of peer
        :param self_id: peer_id of the dialer (to send to receiver)
        :return: True if successful
        """
        host = maddr.value_for_protocol("ip4")
        port = int(maddr.value_for_protocol("tcp"))

        reader, writer = await asyncio.open_connection(host, port)

        # First: send our peer ID so receiver knows it
        writer.write(self_id.to_base58().encode())
        await writer.drain()

        # Await ack for peer id
        expected_ack_str = "received peer id"
        ack = (await reader.read(len(expected_ack_str))).decode()

        if ack != expected_ack_str:
            raise Exception("Receiver did not receive peer id")

        return RawConnection(host, str(port), reader, writer, True)

    def create_listener(self, handler_function: THandler) -> TCPListener:
        """
        create listener on transport
        :param handler_function: a function called when a new connection is received
        that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        return TCPListener(handler_function)


def _multiaddr_from_socket(socket: socket) -> Multiaddr:
    return Multiaddr("/ip4/%s/tcp/%s" % socket.getsockname())

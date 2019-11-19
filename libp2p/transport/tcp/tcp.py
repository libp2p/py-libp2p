import logging
from socket import socket
from typing import List

from multiaddr import Multiaddr
import trio

from libp2p.io.trio import TrioReadWriteCloser
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.listener_interface import IListener
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.typing import THandler

logger = logging.getLogger("libp2p.transport.tcp")


class TCPListener(IListener):
    multiaddrs: List[Multiaddr]
    server = None

    def __init__(self, handler_function: THandler) -> None:
        self.multiaddrs = []
        self.server = None
        self.handler = handler_function

    async def listen(self, maddr: Multiaddr, nursery) -> bool:
        """
        put listener in listening mode and wait for incoming connections.

        :param maddr: maddr of peer
        :return: return True if successful
        """

        async def serve_tcp(handler, port, host, task_status=None):
            logger.debug("serve_tcp %s %s", host, port)
            await trio.serve_tcp(handler, port, host=host, task_status=task_status)

        async def handler(stream):
            read_write_closer = TrioReadWriteCloser(stream)
            await self.handler(read_write_closer)

        listeners = await nursery.start(
            serve_tcp,
            handler,
            int(maddr.value_for_protocol("tcp")),
            maddr.value_for_protocol("ip4"),
        )
        socket = listeners[0].socket
        self.multiaddrs.append(_multiaddr_from_socket(socket))

        return True

    def get_addrs(self) -> List[Multiaddr]:
        """
        retrieve list of addresses the listener is listening on.

        :return: return list of addrs
        """
        # TODO check if server is listening
        return self.multiaddrs

    async def close(self) -> None:
        """close the listener such that no more connections can be open on this
        transport instance."""
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None


class TCP(ITransport):
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        dial a transport to peer listening on multiaddr.

        :param maddr: multiaddr of peer
        :return: `RawConnection` if successful
        :raise OpenConnectionError: raised when failed to open connection
        """
        self.host = maddr.value_for_protocol("ip4")
        self.port = int(maddr.value_for_protocol("tcp"))

        stream = await trio.open_tcp_stream(self.host, self.port)
        read_write_closer = TrioReadWriteCloser(stream)

        return RawConnection(read_write_closer, True)

    def create_listener(self, handler_function: THandler) -> TCPListener:
        """
        create listener on transport.

        :param handler_function: a function called when a new connection is received
            that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        return TCPListener(handler_function)


def _multiaddr_from_socket(socket: socket) -> Multiaddr:
    return Multiaddr("/ip4/%s/tcp/%s" % socket.getsockname())

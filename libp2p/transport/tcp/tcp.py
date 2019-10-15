import asyncio
from socket import socket
from typing import Awaitable, Callable, List

from multiaddr import Multiaddr

from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.listener_interface import IListener
from libp2p.transport.tcp.tcp_stream import TCPStream
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.typing import THandler


# function needed for because asyncio.start_server accepts handlers that receive just TCP Stream,
# instead we use a generic inteface (IStreamReader, IStreamWriter)
def streams_handler_wrapper(
    handler: THandler
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
    async def wrapper(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        return await handler(*TCPStream.from_asyncio_streams(reader, writer))

    return wrapper


class TCPListener(IListener):
    multiaddrs: List[Multiaddr]
    server = None

    def __init__(self, handler_function: THandler) -> None:
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
            streams_handler_wrapper(self.handler),
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

    async def close(self) -> None:
        """
        close the listener such that no more connections
        can be open on this transport instance
        """
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None


class TCP(ITransport):
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        dial a transport to peer listening on multiaddr
        :param maddr: multiaddr of peer
        :return: `RawConnection` if successful
        :raise OpenConnectionError: raised when failed to open connection
        """
        self.host = maddr.value_for_protocol("ip4")
        self.port = int(maddr.value_for_protocol("tcp"))

        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except (ConnectionAbortedError, ConnectionRefusedError) as error:
            raise OpenConnectionError(error)

        stream_reader, stream_writer = TCPStream.from_asyncio_streams(reader, writer)

        return RawConnection(stream_reader, stream_writer, True)

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

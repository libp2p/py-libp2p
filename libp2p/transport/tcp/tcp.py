import asyncio
import socket
import sys
from typing import List, Optional

from multiaddr import Multiaddr
from multiaddr.protocols import P_IP4, P_IP6, P_TCP, P_UDP
from multiaddr.protocols import protocol_with_code as p_code

from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.listener_interface import IListener
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.typing import THandler


class TCPListener(IListener):
    multiaddrs: List[Multiaddr]
    server = None

    def __init__(self, handler_function: THandler) -> None:
        self.multiaddrs = []
        self.server = None
        self.handler = handler_function

    async def listen(self, maddr: Multiaddr) -> bool:
        """
        put listener in listening mode and wait for incoming connections.

        :param maddr: maddr of peer
        :return: return True if successful
        """
        listen_addr = _ip4_or_6_from_multiaddr(maddr)
        if listen_addr is None:
            raise NotImplementedError(
                "Can only start TCP Listener with a IPv4 or IPv6 address"
            )

        self.server = await asyncio.start_server(
            self.handler, listen_addr, maddr.value_for_protocol("tcp")
        )
        socket = self.server.sockets[0]
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
        server = self.server
        self.server = None
        if sys.version_info < (3, 7):
            return
        await server.wait_closed()


class TCP(ITransport):
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        dial a transport to peer listening on multiaddr.

        :param maddr: multiaddr of peer
        :return: `RawConnection` if successful
        :raise OpenConnectionError: raised when failed to open connection
        """
        self.host = _ip4_or_6_from_multiaddr(maddr)
        if self.host is None:
            raise ValueError("Cannot find ipv4 or ipv6 host in multiaddress")

        self.port = int(maddr.value_for_protocol("tcp"))

        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
        except (ConnectionAbortedError, ConnectionRefusedError) as error:
            raise OpenConnectionError(error)

        return RawConnection(reader, writer, True)

    def create_listener(self, handler_function: THandler) -> TCPListener:
        """
        create listener on transport.

        :param handler_function: a function called when a new connection is received
            that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        return TCPListener(handler_function)


def _ip4_or_6_from_multiaddr(maddr: Multiaddr) -> Optional[str]:
    if P_IP4 in maddr.protocols():
        return maddr.value_for_protocol(P_IP4)
    elif P_IP6 in maddr.protocols():
        return maddr.value_for_protocol(P_IP6)
    else:
        return None


def _multiaddr_from_socket(sock: socket.socket) -> Multiaddr:
    # Reference: http://man7.org/linux/man-pages/man2/socket.2.html#DESCRIPTION
    # todo: move this to more generic libp2p.transport helper function

    # Reference: https://stackoverflow.com/questions/5815675/what-is-sock-dgram-and-sock-stream
    # Selects first protocol in sequence if bitwise AND matches, else None
    t_proto = next(
        (
            v
            for k, v in {
                socket.SOCK_STREAM: p_code(P_TCP).name,
                socket.SOCK_DGRAM: p_code(P_UDP).name,
            }.items()
            if k & sock.type != 0
        ),
        None,
    )

    if t_proto is None:
        raise NotImplementedError(
            f"Cannot convert socket to multiaddr, socket type is of {sock.type}"
        )

    # Reference: https://docs.python.org/3/library/socket.html#socket-families
    if sock.family == socket.AF_INET:
        # ipv4: (host, port)
        addr, port = sock.getsockname()
        ip = p_code(P_IP4).name

    elif sock.family == socket.AF_INET6:
        # ipv6: (host, port, flowinfo, scopeid)
        addr, port = sock.getsockname()[:2]
        ip = p_code(P_IP6).name

    else:
        raise NotImplementedError(
            f"Cannot convert socket to multiaddr, socket family is of {sock.family}"
        )

    return Multiaddr(f"/{ip}/{addr}/{t_proto}/{port}")

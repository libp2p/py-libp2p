from collections.abc import (
    Awaitable,
    Sequence,
)
import logging
from typing import (
    Callable,
)

from multiaddr import (
    Multiaddr,
)
import trio
from trio_typing import (
    TaskStatus,
)

from libp2p.abc import (
    IListener,
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import (
    THandler,
)
from libp2p.io.trio import (
    TrioTCPStream,
)
from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.transport.exceptions import (
    OpenConnectionError,
)

logger = logging.getLogger("libp2p.transport.tcp")


class TCPListener(IListener):
    listeners: list[trio.SocketListener]

    def __init__(self, handler_function: THandler) -> None:
        self.listeners = []
        self.handler = handler_function

    # TODO: Get rid of `nursery`?
    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> None:
        """
        Put listener in listening mode and wait for incoming connections.

        :param maddr: maddr of peer
        :return: return True if successful
        """

        async def serve_tcp(
            handler: Callable[[trio.SocketStream], Awaitable[None]],
            port: int,
            host: str,
            task_status: TaskStatus[Sequence[trio.SocketListener]] = None,
        ) -> None:
            """Just a proxy function to add logging here."""
            logger.debug("serve_tcp %s %s", host, port)
            await trio.serve_tcp(handler, port, host=host, task_status=task_status)

        async def handler(stream: trio.SocketStream) -> None:
            remote_host: str = ""
            remote_port: int = 0
            try:
                tcp_stream = TrioTCPStream(stream)
                remote_host, remote_port = tcp_stream.get_remote_address()
                await self.handler(tcp_stream)
            except Exception:
                logger.debug(f"Connection from {remote_host}:{remote_port} failed.")

        listeners = await nursery.start(
            serve_tcp,
            handler,
            int(maddr.value_for_protocol("tcp")),
            maddr.value_for_protocol("ip4"),
        )
        self.listeners.extend(listeners)

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Retrieve list of addresses the listener is listening on.

        :return: return list of addrs
        """
        return tuple(
            _multiaddr_from_socket(listener.socket) for listener in self.listeners
        )

    async def close(self) -> None:
        async with trio.open_nursery() as nursery:
            for listener in self.listeners:
                nursery.start_soon(listener.aclose)


class TCP(ITransport):
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        Dial a transport to peer listening on multiaddr.

        :param maddr: multiaddr of peer
        :return: `RawConnection` if successful
        :raise OpenConnectionError: raised when failed to open connection
        """
        self.host = maddr.value_for_protocol("ip4")
        self.port = int(maddr.value_for_protocol("tcp"))

        try:
            stream = await trio.open_tcp_stream(self.host, self.port)
        except OSError as error:
            raise OpenConnectionError from error
        read_write_closer = TrioTCPStream(stream)

        return RawConnection(read_write_closer, True)

    def create_listener(self, handler_function: THandler) -> TCPListener:
        """
        Create listener on transport.

        :param handler_function: a function called when a new connection is received
            that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        return TCPListener(handler_function)


def _multiaddr_from_socket(socket: trio.socket.SocketType) -> Multiaddr:
    ip, port = socket.getsockname()
    return Multiaddr(f"/ip4/{ip}/tcp/{port}")

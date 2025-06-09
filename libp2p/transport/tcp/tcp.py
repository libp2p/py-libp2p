from collections.abc import (
    Awaitable,
    Callable,
    Sequence,
)
import logging

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
    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Put listener in listening mode and wait for incoming connections.

        :param maddr: maddr of peer
        :return: return True if successful
        """

        async def serve_tcp(
            handler: Callable[[trio.SocketStream], Awaitable[None]],
            port: int,
            host: str,
            task_status: TaskStatus[Sequence[trio.SocketListener]],
        ) -> None:
            """Just a proxy function to add logging here."""
            logger.debug("serve_tcp %s %s", host, port)
            await trio.serve_tcp(handler, port, host=host, task_status=task_status)

        async def handler(stream: trio.SocketStream) -> None:
            remote_host: str = ""
            remote_port: int = 0
            try:
                tcp_stream = TrioTCPStream(stream)
                remote_tuple = tcp_stream.get_remote_address()

                if remote_tuple is not None:
                    remote_host, remote_port = remote_tuple

                await self.handler(tcp_stream)
            except Exception:
                logger.debug(f"Connection from {remote_host}:{remote_port} failed.")

        tcp_port_str = maddr.value_for_protocol("tcp")
        if tcp_port_str is None:
            logger.error(f"Cannot listen: TCP port is missing in multiaddress {maddr}")
            return False

        try:
            tcp_port = int(tcp_port_str)
        except ValueError:
            logger.error(
                f"Cannot listen: Invalid TCP port '{tcp_port_str}' "
                f"in multiaddress {maddr}"
            )
            return False

        ip4_host_str = maddr.value_for_protocol("ip4")
        # For trio.serve_tcp, ip4_host_str (as host argument) can be None,
        # which typically means listen on all available interfaces.

        started_listeners = await nursery.start(
            serve_tcp,
            handler,
            tcp_port,
            ip4_host_str,
        )

        if started_listeners is None:
            # This implies that task_status.started() was not called within serve_tcp,
            # likely because trio.serve_tcp itself failed to start (e.g., port in use).
            logger.error(
                f"Failed to start TCP listener for {maddr}: "
                f"`nursery.start` returned None. "
                "This might be due to issues like the port already "
                "being in use or invalid host."
            )
            return False

        self.listeners.extend(started_listeners)
        return True

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
        host_str = maddr.value_for_protocol("ip4")
        port_str = maddr.value_for_protocol("tcp")

        if host_str is None:
            raise OpenConnectionError(
                f"Failed to dial {maddr}: IP address not found in multiaddr."
            )

        if port_str is None:
            raise OpenConnectionError(
                f"Failed to dial {maddr}: TCP port not found in multiaddr."
            )

        try:
            port_int = int(port_str)
        except ValueError:
            raise OpenConnectionError(
                f"Failed to dial {maddr}: Invalid TCP port '{port_str}'."
            )

        try:
            # trio.open_tcp_stream requires host to be str or bytes, not None.
            stream = await trio.open_tcp_stream(host_str, port_int)
        except OSError as error:
            # OSError is common for network issues like "Connection refused"
            # or "Host unreachable".
            raise OpenConnectionError(
                f"Failed to open TCP stream to {maddr}: {error}"
            ) from error
        except Exception as error:
            # Catch other potential errors from trio.open_tcp_stream and wrap them.
            raise OpenConnectionError(
                f"An unexpected error occurred when dialing {maddr}: {error}"
            ) from error

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

from collections.abc import (
    Awaitable,
    Callable,
    Sequence,
)
import logging

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver
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
from libp2p.utils.multiaddr_utils import (
    extract_ip_from_multiaddr,
    multiaddr_from_socket,
)

logger = logging.getLogger(__name__)


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

        host_str = extract_ip_from_multiaddr(maddr)
        # For trio.serve_tcp, host_str (as host argument) can be None,
        # which typically means listen on all available interfaces.

        started_listeners = await nursery.start(
            serve_tcp,
            handler,
            tcp_port,
            host_str,
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

        Resolves DNS (dns, dns4, dns6, dnsaddr) before dialing (Phase 3.1).

        :param maddr: multiaddr of peer
        :return: `RawConnection` if successful
        :raise OpenConnectionError: raised when failed to open connection
        """
        protocols = list(maddr.protocols())
        dns_protocols = {"dns", "dns4", "dns6", "dnsaddr"}
        if protocols and protocols[0].name in dns_protocols:
            try:
                resolver = DNSResolver()
                resolved = await resolver.resolve(maddr)
            except Exception as e:
                logger.warning("DNS resolution failed for %s: %s", maddr, e)
                raise OpenConnectionError(
                    f"Failed to resolve DNS for {maddr}: {e}"
                ) from e
            if not resolved:
                raise OpenConnectionError(
                    f"No addresses resolved for DNS multiaddr: {maddr}"
                )
            last_error: Exception | None = None
            for resolved_addr in resolved:
                try:
                    return await self._dial_resolved(resolved_addr)
                except Exception as e:
                    last_error = e
                    logger.debug(
                        "Dial to resolved address %s failed: %s", resolved_addr, e
                    )
                    continue
            if last_error is not None:
                raise OpenConnectionError(
                    f"Failed to connect to any resolved address for {maddr}"
                ) from last_error
            raise OpenConnectionError(
                f"Failed to connect to any resolved address for {maddr}"
            )
        return await self._dial_resolved(maddr)

    async def _dial_resolved(self, maddr: Multiaddr) -> IRawConnection:
        """Dial using a multiaddr that has an IP (no DNS)."""
        host_str = extract_ip_from_multiaddr(maddr)
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
            logger.debug("=== OPENING TCP STREAM ===")
            logger.debug("Host: %s", host_str)
            logger.debug("Port: %d", port_int)
            stream = await trio.open_tcp_stream(host_str, port_int)
            logger.debug("Successfully opened TCP stream")
        except OSError as error:
            logger.error("Failed to open TCP stream: %s", error)
            raise OpenConnectionError(
                f"Failed to open TCP stream to {maddr}: {error}"
            ) from error
        except Exception as error:
            logger.error("Unexpected error opening TCP stream: %s", error)
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
    return multiaddr_from_socket(socket)

from collections.abc import (
    Awaitable,
    Callable,
    Sequence,
)
import logging

from multiaddr import Multiaddr
from multiaddr.exceptions import ProtocolLookupError
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
from libp2p.utils.dns_utils import resolve_multiaddr_with_retry
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
        # Internal concurrency state — see listen() / close().
        self._nursery: trio.Nursery | None = None
        self._started: trio.Event = trio.Event()
        self._stopped: trio.Event = trio.Event()
        self._start_error: BaseException | None = None

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Put listener in listening mode and wait for incoming connections.

        The listener spawns its own internal nursery as a trio system task
        so that ``serve_tcp`` keeps running after ``listen()`` returns.
        The nursery is cancelled on :meth:`close`.

        :param maddr: maddr of peer
        :raises OpenConnectionError: if listening fails (e.g. missing/invalid
            port or failed start)
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

        try:
            tcp_port_str = maddr.value_for_protocol("tcp")
        except ProtocolLookupError:
            error_msg = f"Cannot listen: TCP port is missing in multiaddress {maddr}"
            logger.error(error_msg)
            raise OpenConnectionError(error_msg) from None

        if tcp_port_str is None:
            error_msg = f"Cannot listen: TCP port is missing in multiaddress {maddr}"
            raise OpenConnectionError(error_msg)

        try:
            tcp_port = int(tcp_port_str)
        except ValueError:
            error_msg = (
                f"Cannot listen: Invalid TCP port '{tcp_port_str}' "
                f"in multiaddress {maddr}"
            )
            logger.error(error_msg)
            raise OpenConnectionError(error_msg)

        host_str = extract_ip_from_multiaddr(maddr)
        # For trio.serve_tcp, host_str (as host argument) can be None,
        # which typically means listen on all available interfaces.

        # Reset state in case of a re-listen.
        self._started = trio.Event()
        self._stopped = trio.Event()
        self._start_error = None

        async def _run_server() -> None:
            try:
                async with trio.open_nursery() as nursery:
                    self._nursery = nursery
                    try:
                        started_listeners = await nursery.start(
                            serve_tcp,
                            handler,
                            tcp_port,
                            host_str,
                        )
                        self.listeners.extend(started_listeners)
                    except BaseException as error:
                        self._start_error = error
                    finally:
                        self._started.set()
                    # Nursery stays open serving connections until cancelled
                    # from close().
            finally:
                self._stopped.set()
                self._nursery = None

        trio.lowlevel.spawn_system_task(_run_server)
        await self._started.wait()

        if self._start_error is not None:
            error_msg = (
                f"Failed to start TCP listener for {maddr}: {self._start_error}"
            )
            logger.error(error_msg)
            raise OpenConnectionError(error_msg) from self._start_error

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Retrieve list of addresses the listener is listening on.

        :return: return list of addrs
        """
        return tuple(
            _multiaddr_from_socket(listener.socket) for listener in self.listeners
        )

    async def close(self) -> None:
        """
        Cancel the listener's internal nursery and close all sockets.

        Safe to call multiple times.  Waits for the background system task
        to finish before returning.
        """
        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()

        async with trio.open_nursery() as nursery:
            for listener in self.listeners:
                nursery.start_soon(listener.aclose)
        self.listeners.clear()

        # Wait for the background _run_server task to finish cleaning up.
        if self._started.is_set():
            await self._stopped.wait()


class TCP(ITransport):
    def __init__(
        self,
        *,
        dns_resolution_timeout: float = 5.0,
        dns_max_retries: int = 3,
    ) -> None:
        """
        :param dns_resolution_timeout: Per-attempt timeout in seconds for DNS.
        :param dns_max_retries: Max DNS resolution attempts (with backoff).
        """
        self._dns_resolution_timeout = dns_resolution_timeout
        self._dns_max_retries = dns_max_retries

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
            resolved = await resolve_multiaddr_with_retry(
                maddr,
                resolver=DNSResolver(),
                max_retries=self._dns_max_retries,
                timeout_seconds=self._dns_resolution_timeout,
            )
            if not resolved:
                raise OpenConnectionError(
                    f"Failed to resolve DNS for {maddr} (retries exhausted)"
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

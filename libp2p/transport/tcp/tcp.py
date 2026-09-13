from collections.abc import (
    Awaitable,
    Callable,
    Sequence,
)
import logging
import socket as stdlib_socket
import typing

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


def _set_reuse_flags(sock: trio.socket.SocketType) -> None:
    """
    Best-effort SO_REUSEADDR/SO_REUSEPORT for TCP hole punching.

    Hole punching (DCUtR simultaneous open) requires dialing FROM the
    listen port, which means the listener and outbound dial sockets must
    share the same (ip, port). On Linux this needs SO_REUSEPORT on both.
    Failures are ignored (e.g. platforms without SO_REUSEPORT) — callers
    fall back to normal behaviour.
    """
    try:
        sock.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEADDR, 1)
    except OSError:
        pass
    try:
        sock.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass


async def _open_reuseport_listeners(
    host: str | None, port: int
) -> list[trio.SocketListener]:
    """
    Open TCP listen sockets with SO_REUSEPORT (mirrors ``trio.serve_tcp``
    address resolution, but allows hole-punch dials to bind the same port).
    """
    if host is None:
        # Match trio.serve_tcp(host=None): listen on all interfaces.
        targets: list[tuple[int, str]] = [
            (trio.socket.AF_INET, "0.0.0.0"),
        ]
        try:
            targets.append((trio.socket.AF_INET6, "::"))
        except Exception:
            pass
    elif ":" in host:
        targets = [(trio.socket.AF_INET6, host)]
    else:
        targets = [(trio.socket.AF_INET, host)]

    listeners: list[trio.SocketListener] = []
    last_error: Exception | None = None
    for family, ip in targets:
        try:
            sock = trio.socket.socket(family, stdlib_socket.SOCK_STREAM)
        except OSError as e:
            last_error = e
            logger.debug("reuseport socket create for %s:%d failed: %s", ip, port, e)
            continue
        _set_reuse_flags(sock)
        try:
            await sock.bind((ip, port))
            sock.listen(128)
        except OSError as e:
            last_error = e
            logger.debug("reuseport listen on %s:%d failed: %s", ip, port, e)
            try:
                sock.close()
            except Exception:
                pass
            continue
        # SocketListener requires an already-listening socket: wrap last.
        try:
            listeners.append(trio.SocketListener(sock))
        except Exception as e:
            last_error = e
            logger.debug("SocketListener wrap for %s:%d failed: %s", ip, port, e)
            try:
                sock.close()
            except Exception:
                pass
            continue
    if not listeners:
        raise OpenConnectionError(f"Failed to listen on {host}:{port}: {last_error}")
    return listeners


async def _open_tcp_stream_from(
    host: str, port: int, source: tuple[str, int]
) -> trio.SocketStream:
    """
    Open a TCP stream bound to ``source`` (ip, port).

    Used for hole punching: the SYN must leave from the listen port so the
    NAT mapping lines up with the advertised external address.
    """
    src_ip, src_port = source
    family = trio.socket.AF_INET6 if ":" in host else trio.socket.AF_INET
    if (":" in src_ip) != (":" in host):
        raise OpenConnectionError(
            f"Source/destination IP family mismatch: {src_ip} vs {host}"
        )
    try:
        sock = trio.socket.socket(family, stdlib_socket.SOCK_STREAM)
    except OSError as e:
        raise OpenConnectionError(f"Failed to create TCP socket: {e}") from e
    _set_reuse_flags(sock)
    try:
        await sock.bind((src_ip, src_port))
    except OSError as e:
        # Platform cannot share the listen port for outbound dials (e.g.
        # macOS refuses connect() from a bound listening port). Fall back
        # to an ephemeral source: direct connections still work, only NAT
        # hole punching (which needs the bound source) is unavailable there.
        logger.debug(
            "Hole-punch source bind %s:%d failed (%s); using ephemeral source",
            src_ip,
            src_port,
            e,
        )
        sock.close()
        try:
            return await trio.open_tcp_stream(host, port)
        except OSError as conn_e:
            raise OpenConnectionError(
                f"Failed to connect {host}:{port}: {conn_e}"
            ) from conn_e
    try:
        await sock.connect((host, port))
    except OSError as e:
        sock.close()
        raise OpenConnectionError(
            f"Failed to connect {host}:{port} from {src_ip}:{src_port}: {e}"
        ) from e
    return trio.SocketStream(sock)


class TCPListener(IListener):
    listeners: list[trio.SocketListener]

    def __init__(self, handler_function: THandler) -> None:
        self.listeners = []
        self.handler = handler_function
        # Internal concurrency state — see listen() / close().
        self._nursery: trio.Nursery | None = None
        self._nursery_ready: trio.Event = trio.Event()
        self._stopped: trio.Event = trio.Event()
        self._closed: bool = False
        # Serializes listen()/close() so concurrent callers don't race the
        # lazy system-task spawn.
        self._lifecycle_lock: trio.Lock = trio.Lock()

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Put listener in listening mode and wait for incoming connections.

        On the first call, the listener spawns its own internal nursery as
        a trio system task so that ``serve_tcp`` keeps running after
        ``listen()`` returns. Subsequent calls add additional binds to the
        same nursery. The nursery is cancelled on :meth:`close`.

        :param maddr: maddr of peer
        :raises OpenConnectionError: if listening fails (e.g. missing/invalid
            port, failed start, or listener already closed)
        """

        async def serve_tcp(
            handler: Callable[[trio.SocketStream], Awaitable[None]],
            port: int,
            host: str,
            task_status: TaskStatus[Sequence[trio.SocketListener]],
        ) -> None:
            """
            Serve with SO_REUSEPORT sockets so hole-punch dials can
            bind the same (ip, port) for TCP simultaneous open.
            """
            logger.debug("serve_tcp %s %s", host, port)
            listeners = await _open_reuseport_listeners(host, port)
            # TaskStatus is invariant: SocketListener satisfies
            # Listener[SocketStream] but the declared types differ.
            serve_status = typing.cast(
                TaskStatus[typing.Sequence[trio.abc.Listener[trio.SocketStream]]],
                task_status,
            )
            await trio.serve_listeners(handler, listeners, task_status=serve_status)

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

        async with self._lifecycle_lock:
            if self._closed:
                raise OpenConnectionError(
                    f"Cannot listen on {maddr}: listener is closed"
                )
            if self._nursery is None:
                await self._spawn_background_task()

            nursery = self._nursery
            if nursery is None:
                raise OpenConnectionError(
                    f"Cannot listen on {maddr}: background task is not running"
                )
            try:
                started_listeners = await nursery.start(
                    typing.cast(typing.Any, serve_tcp),
                    handler,
                    tcp_port,
                    host_str,
                )
            except BaseException as error:
                error_msg = f"Failed to start TCP listener for {maddr}: {error}"
                logger.error(error_msg)
                raise OpenConnectionError(error_msg) from error
            self.listeners.extend(started_listeners)

    async def _spawn_background_task(self) -> None:
        """Spawn the nursery-owning system task and await its readiness."""

        async def _run_server() -> None:
            try:
                async with trio.open_nursery() as nursery:
                    self._nursery = nursery
                    self._nursery_ready.set()
                    # Keep the nursery body alive so it stays open for
                    # subsequent nursery.start(serve_tcp, ...) calls from
                    # listen(). close() cancels the scope to unblock this;
                    # the nursery's cancel scope consumes the Cancelled.
                    await trio.sleep_forever()
            finally:
                self._nursery = None
                self._stopped.set()

        trio.lowlevel.spawn_system_task(_run_server)
        await self._nursery_ready.wait()

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

        Safe to call multiple times. Once closed, further :meth:`listen`
        calls raise ``OpenConnectionError``. Waits for the background
        system task to finish before returning.
        """
        async with self._lifecycle_lock:
            already_closed = self._closed
            self._closed = True
            if self._nursery is not None:
                self._nursery.cancel_scope.cancel()

        if already_closed:
            # First call already tore everything down; nothing to do.
            return

        async with trio.open_nursery() as nursery:
            for listener in self.listeners:
                nursery.start_soon(listener.aclose)
        self.listeners.clear()

        # Wait for the background _run_server task to finish cleaning up.
        if self._nursery_ready.is_set():
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

    async def dial_with_source(
        self, maddr: Multiaddr, source: tuple[str, int]
    ) -> IRawConnection:
        """
        Dial like :meth:`dial` but bind the outbound socket to ``source``
        (ip, port) first.

        Used for TCP hole punching (DCUtR simultaneous open): the SYN must
        leave from the listen port so the NAT mapping matches the advertised
        external address. Requires the listener to have SO_REUSEPORT (set
        by :class:`TCPListener`).
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
                    return await self._dial_resolved(resolved_addr, source=source)
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
        return await self._dial_resolved(maddr, source=source)

    async def _dial_resolved(
        self, maddr: Multiaddr, source: tuple[str, int] | None = None
    ) -> IRawConnection:
        """Dial using a multiaddr that has an IP (no DNS)."""
        host_str = extract_ip_from_multiaddr(maddr)
        try:
            port_str = maddr.value_for_protocol("tcp")
        except ProtocolLookupError as error:
            # Defence in depth: Swarm/TransportManager should filter these via
            # can_dial(), but match listen()'s handling if a bad addr slips through.
            raise OpenConnectionError(
                f"Failed to dial {maddr}: no TCP component in multiaddr."
            ) from error

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
            if source is None:
                stream = await trio.open_tcp_stream(host_str, port_int)
            else:
                stream = await _open_tcp_stream_from(host_str, port_int, source)
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

    def can_dial(self, maddr: Multiaddr) -> bool:
        """
        Return True if this TCP transport can dial the given multiaddr.

        Accepts pure TCP addresses (/ip4/.../tcp/... or /ip6/.../tcp/...) but
        rejects WebSocket addresses (/ws, /wss) even though they use TCP underneath,
        so the TransportManager routes those to WebsocketTransport instead.

        :param maddr: The multiaddress to check.
        :return: True if this transport handles the multiaddr.
        """
        names = {p.name for p in maddr.protocols()}
        return "tcp" in names and not names.intersection(
            {"ws", "wss", "quic", "quic-v1"}
        )

    def can_listen(self, maddr: Multiaddr) -> bool:
        """
        Return True if this TCP transport can listen on the given multiaddr.

        :param maddr: The multiaddress to check.
        :return: True if this transport can listen on the multiaddr.
        """
        return self.can_dial(maddr)

    def protocols(self) -> list[str]:
        """
        Return the list of multiaddr protocol names handled by TCP transport.

        :return: ["tcp"]
        """
        return ["tcp"]


def _multiaddr_from_socket(socket: trio.socket.SocketType) -> Multiaddr:
    return multiaddr_from_socket(socket)

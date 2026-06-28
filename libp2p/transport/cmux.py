from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from enum import IntEnum
import logging
from typing import TYPE_CHECKING, Any

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.io.peekable_stream import PeekableStream
from libp2p.transport.exceptions import OpenConnectionError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Matches go-libp2p's tcpreuse.acceptQueueSize = 64.
# Limits how many classified connections can wait before being consumed by their
# per-type listener.  If the queue is full the connection is dropped after
# ACCEPT_TIMEOUT seconds (mirrors go-libp2p's acceptTimeout = 30s).
ACCEPT_QUEUE_SIZE = 64
ACCEPT_TIMEOUT = 30.0

# go-libp2p peeks exactly 3 bytes to classify connections.
_PEEK_SIZE = 3
# Timeout for reading the classification bytes from a new connection.
_IDENTIFY_TIMEOUT = 5.0


class DemultiplexedConnType(IntEnum):
    """
    Mirrors ``tcpreuse.DemultiplexedConnType`` from go-libp2p.

    Used to route an incoming TCP connection to the correct transport listener
    after peeking at the first 3 bytes of the stream.
    """

    UNKNOWN = 0
    #: Raw libp2p TCP connections start with the multistream-select header
    #: ``\\x13/multistream/1.0.0\\n``.  The first 3 bytes are ``\\x13/m``.
    MULTISTREAM_SELECT = 1
    #: WebSocket (plain) connections start with an HTTP upgrade request.
    #: Matches GET / HEAD / POST / PUT / DELETE / CONNECT / OPTIONS /
    #: TRACE / PATCH and also PRI (HTTP/2 cleartext preface).
    HTTP = 2
    #: WebSocket-Secure (WSS) connections are wrapped in TLS.
    #: Matches TLS 1.0–1.3 ``ClientHello`` record headers.
    TLS = 3


# ---------------------------------------------------------------------------
# 3-byte classifier – mirrors go-libp2p identifyConnType / IsMultistreamSelect
# ---------------------------------------------------------------------------

_HTTP_PREFIXES: frozenset[bytes] = frozenset(
    [
        b"GET",
        b"HEA",
        b"POS",
        b"PUT",
        b"DEL",
        b"CON",
        b"OPT",
        b"TRA",
        b"PAT",
        # HTTP/2 cleartext preface "PRI * HTTP/2.0\r\n…"
        b"PRI",
    ]
)

_TLS_PREFIXES: frozenset[bytes] = frozenset(
    [
        b"\x16\x03\x01",  # TLS 1.0 / 1.2 ClientHello record
        b"\x16\x03\x02",  # TLS 1.1
        b"\x16\x03\x03",  # TLS 1.3
    ]
)


def identify_conn_type(prefix: bytes) -> DemultiplexedConnType:
    """
    Classify a connection from its first 3 bytes.

    Directly mirrors ``tcpreuse.identifyConnType`` / ``IsMultistreamSelect`` /
    ``IsHTTP`` / ``IsTLS`` from go-libp2p.

    :param prefix: Exactly 3 bytes read from the start of the stream.
    :returns: The detected :class:`DemultiplexedConnType`.
    """
    if len(prefix) < 3:
        return DemultiplexedConnType.UNKNOWN
    if prefix == b"\x13/m":
        return DemultiplexedConnType.MULTISTREAM_SELECT
    if prefix in _TLS_PREFIXES:
        return DemultiplexedConnType.TLS
    if prefix in _HTTP_PREFIXES:
        return DemultiplexedConnType.HTTP
    return DemultiplexedConnType.UNKNOWN


# ---------------------------------------------------------------------------
# DemultiplexedListener – per-connection-type listener (channel consumer)
# ---------------------------------------------------------------------------


class DemultiplexedListener(IListener):
    """
    A listener that receives pre-classified connections from :class:`PortDemultiplexer`.

    Each instance holds one end of a :func:`trio.open_memory_channel` and
    exposes an ``accept()`` async iterator consumed by the transport that
    registered for this connection type.

    When a *conn_handler* is provided, :meth:`listen` spawns a background Trio
    task that drains the channel and calls the handler for every incoming
    connection.  This is the Trio equivalent of the goroutine that reads from a
    buffered ``chan *connWithScope`` in go-libp2p's ``demultiplexedListener``.

    Mirrors ``tcpreuse.demultiplexedListener`` from go-libp2p.
    """

    def __init__(
        self,
        conn_type: DemultiplexedConnType,
        recv_channel: trio.MemoryReceiveChannel[PeekableStream],
        listen_maddr: Multiaddr,
        close_callback: object,
        conn_handler: object = None,
    ) -> None:
        self.conn_type = conn_type
        self._recv = recv_channel
        self._listen_maddr = listen_maddr
        self._close_callback = close_callback
        self._closed = False
        # Optional handler called per-connection by the drain task.
        self._conn_handler = conn_handler
        self._nursery: trio.Nursery | None = None
        self._cancel_scope: trio.CancelScope | None = None

    async def connections(self) -> AsyncIterator[PeekableStream]:
        """Async-iterate over pre-classified connections."""
        async with self._recv:
            async for conn in self._recv:
                yield conn

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        return (self._listen_maddr,) if self._listen_maddr else ()

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Start the connection-drain loop (no-op when no handler is registered).

        When a *conn_handler* was supplied, this spawns a Trio system task that
        continuously reads :class:`PeekableStream` objects from the channel and
        calls the handler for each one.  The actual TCP socket is created by
        :class:`PortDemultiplexer` — this method only starts the consumer side.
        """
        if self._conn_handler is None:
            # No handler: caller will consume via .connections() directly.
            return

        handler = self._conn_handler  # capture for closure

        async def _drain() -> None:
            try:
                with trio.CancelScope(**{}) as cancel_scope:
                    self._cancel_scope = cancel_scope
                    async with trio.open_nursery() as nursery:
                        self._nursery = nursery
                        async with self._recv:
                            async for stream in self._recv:
                                nursery.start_soon(self._run_handler, handler, stream)
            except Exception:
                pass
            except BaseException:
                pass

        nursery = getattr(self, "background_nursery", None)
        if nursery is not None:
            nursery.start_soon(_drain)
        else:
            trio.lowlevel.spawn_system_task(_drain)

    async def _run_handler(
        self,
        handler: Callable[[trio.abc.Stream], Awaitable[None]],
        stream: PeekableStream,
    ) -> None:
        try:
            await handler(stream)
        except Exception as exc:
            logger.debug("DemultiplexedListener: handler error: %s", exc)

    async def close(self) -> None:
        """Close this demultiplexed listener and remove it from PortDemultiplexer."""
        if self._closed:
            return
        self._closed = True
        self._recv.close()
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
        if callable(self._close_callback):
            self._close_callback(self.conn_type)


# ---------------------------------------------------------------------------
# PortDemultiplexer – shared TCP listener + demultiplexer
# ---------------------------------------------------------------------------


class PortDemultiplexer(IListener):
    """
    Enables sharing a single TCP port between multiple transports.

    Each transport calls :meth:`demultiplexed_listen` with its expected
    :class:`DemultiplexedConnType`.  Internally, one OS-level TCP socket is
    opened and a background task classifies every new connection by peeking at
    its first 3 bytes, then routes it into the matching
    :class:`DemultiplexedListener`'s channel.

    Mirrors ``tcpreuse.PortDemultiplexer`` from go-libp2p (``p2p/transport/tcpreuse``).

    Usage::

        port_demux = PortDemultiplexer("0.0.0.0", 4001)

        # TCP transport registers for raw libp2p connections
        tcp_listener = port_demux.demultiplexed_listen(
            maddr, DemultiplexedConnType.MULTISTREAM_SELECT
        )

        # WebSocket transport registers for HTTP-upgrade connections
        ws_listener = port_demux.demultiplexed_listen(
            maddr, DemultiplexedConnType.HTTP
        )

        await port_demux.listen(maddr)   # binds the socket and starts routing

    """

    host: str
    port: int
    listen_maddr: Multiaddr | None

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.listen_maddr = None

        # Map from conn type → (send_channel, recv_channel) pair.
        # Populated by demultiplexed_listen() before listen() is called.
        self._send_channels: dict[
            DemultiplexedConnType, trio.MemorySendChannel[PeekableStream]
        ] = {}
        self._listeners: dict[DemultiplexedConnType, DemultiplexedListener] = {}

        self._nursery: trio.Nursery | None = None
        self._started: trio.Event = trio.Event()
        self._stopped: trio.Event = trio.Event()
        self._closed: bool = False
        self._start_error: BaseException | None = None

    # ------------------------------------------------------------------
    # Public API – mirrors go-libp2p PortDemultiplexer.DemultiplexedListen()
    # ------------------------------------------------------------------

    def demultiplexed_listen(
        self,
        maddr: Multiaddr,
        conn_type: DemultiplexedConnType,
        conn_handler: object = None,
    ) -> DemultiplexedListener:
        """
        Register a listener for *conn_type* connections on this shared port.

        Must be called **before** :meth:`listen`.  Raises :exc:`ValueError`
        if a listener for the same *conn_type* is already registered (mirrors
        ``tcpreuse.ErrListenerExists``).

        :param maddr: The multiaddress that will be bound (used for
            :meth:`DemultiplexedListener.get_addrs`).
        :param conn_type: The connection type this listener should receive.
        :param conn_handler: Optional async callable called per connection.
            When provided, :meth:`DemultiplexedListener.listen` starts a
            background drain task that calls this handler for each classified
            connection.
        :returns: A :class:`DemultiplexedListener` whose
            :meth:`~DemultiplexedListener.connections` yields classified
            connections.
        :raises ValueError: If *conn_type* already has a registered listener.
        """
        if conn_type == DemultiplexedConnType.UNKNOWN:
            raise ValueError("Cannot register a listener for UNKNOWN conn type")
        if conn_type in self._send_channels:
            raise ValueError(
                f"Listener already exists for conn type {conn_type!r}"
                f" on {self.host}:{self.port}"
            )

        # Update TCP port component of the listen_maddr if it differs from self.port.
        # This handles cases where demultiplexed_listen is called after listen()
        # bound 0.
        from multiaddr import Multiaddr

        parts = str(maddr).split("/")
        for i, part in enumerate(parts):
            if part == "tcp" and i + 1 < len(parts):
                parts[i + 1] = str(self.port)
        real_maddr = Multiaddr("/".join(parts))

        send_ch, recv_ch = trio.open_memory_channel[PeekableStream](ACCEPT_QUEUE_SIZE)
        self._send_channels[conn_type] = send_ch

        def _remove(ct: DemultiplexedConnType) -> None:
            self._send_channels.pop(ct, None)
            self._listeners.pop(ct, None)

        dl = DemultiplexedListener(
            conn_type=conn_type,
            recv_channel=recv_ch,
            listen_maddr=real_maddr,
            close_callback=_remove,
            conn_handler=conn_handler,
        )
        self._listeners[conn_type] = dl
        logger.debug(
            "PortDemultiplexer: registered %s listener on %s:%d",
            conn_type.name,
            self.host,
            self.port,
        )
        return dl

    # ------------------------------------------------------------------
    # IListener.listen – bind the OS socket and start the routing task
    # ------------------------------------------------------------------

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Bind to the port and start the demultiplexing loop.

        Subsequent calls are no-ops if the socket is already bound (mirrors
        go-libp2p where each transport calls ``DemultiplexedListen`` and the
        underlying socket is only created once per address).
        """
        if self._started.is_set():
            return

        async def _serve(
            task_status: Any = trio.TASK_STATUS_IGNORED,
        ) -> None:
            logger.debug("PortDemultiplexer serving on %s:%d", self.host, self.port)
            try:
                await trio.serve_tcp(
                    self._classify_and_route,
                    self.port,
                    host=self.host,
                    task_status=task_status,
                )
            except Exception as exc:
                logger.error("PortDemultiplexer serve error: %s", exc)
                raise

        async def _run_server() -> None:
            try:
                async with trio.open_nursery() as nursery:
                    self._nursery = nursery
                    try:
                        listeners = await nursery.start(_serve)
                        if listeners:
                            sock = listeners[0].socket
                            new_port = sock.getsockname()[1]
                            self.port = new_port
                            for dl in self._listeners.values():
                                if dl._listen_maddr is not None:
                                    # Update the tcp component with the real port
                                    from multiaddr import Multiaddr

                                    parts = str(dl._listen_maddr).split("/")
                                    for i, part in enumerate(parts):
                                        if part == "tcp" and i + 1 < len(parts):
                                            parts[i + 1] = str(new_port)
                                    dl._listen_maddr = Multiaddr("/".join(parts))
                    except BaseException as err:
                        self._start_error = err
                    finally:
                        self._started.set()
            finally:
                self._stopped.set()
                self._nursery = None

        nursery = getattr(self, "background_nursery", None)
        if nursery is not None:
            nursery.start_soon(_run_server)
        else:
            trio.lowlevel.spawn_system_task(_run_server)
        await self._started.wait()

        if self._start_error is not None:
            raise OpenConnectionError(
                f"PortDemultiplexer failed to listen on {maddr}: {self._start_error}"
            )

    # ------------------------------------------------------------------
    # Internal – classify each new connection and route it
    # ------------------------------------------------------------------

    async def _classify_and_route(self, stream: trio.SocketStream) -> None:
        """
        Peek at the first :data:`_PEEK_SIZE` bytes, classify, and dispatch.

        Mirrors ``multiplexedListener.run()`` + ``identifyConnType()`` from
        go-libp2p's ``tcpreuse`` package.
        """
        try:
            peekable = PeekableStream(stream)

            # Read exactly 3 bytes for classification (matches go-libp2p).
            try:
                with trio.fail_after(_IDENTIFY_TIMEOUT):
                    prefix = await peekable.receive_some(_PEEK_SIZE)
            except trio.TooSlowError:
                logger.debug(
                    "PortDemultiplexer: timed out reading classification bytes;"
                    " closing connection"
                )
                await stream.aclose()
                return

            # Prepend the peeked bytes back into the buffer so handlers see a
            # complete stream (mirrors sampledconn.PeekBytes in go-libp2p).
            peekable.buffer = bytearray(prefix) + peekable.buffer

            conn_type = identify_conn_type(prefix)
            logger.debug(
                "PortDemultiplexer: classified connection as %s", conn_type.name
            )

            send_ch = self._send_channels.get(conn_type)
            if send_ch is None:
                logger.debug(
                    "PortDemultiplexer: no registered listener "
                    "for %s; closing connection",
                    conn_type.name,
                )
                await stream.aclose()
                return

            # Create an event to keep the trio.serve_tcp handler alive
            # because trio automatically closes the stream when the handler returns.
            stream_closed = trio.Event()
            peekable.close_callback = stream_closed.set

            # Try to deliver with a bounded timeout to avoid blocking the
            # accept loop (mirrors go-libp2p's acceptTimeout = 30s).
            try:
                with trio.fail_after(ACCEPT_TIMEOUT):
                    await send_ch.send(peekable)
            except (trio.TooSlowError, trio.ClosedResourceError):
                logger.debug(
                    "PortDemultiplexer: accept queue full or listener closed for %s; "
                    "dropping connection",
                    conn_type.name,
                )
                await stream.aclose()
                return

            # Wait for the consumer to finish using and close the stream
            await stream_closed.wait()

        except Exception:
            try:
                await stream.aclose()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # IListener helpers
    # ------------------------------------------------------------------

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Return the multiaddresses this listener is bound to."""
        if self.listen_maddr is not None:
            return (self.listen_maddr,)
        return ()

    async def close(self) -> None:
        """Close all registered listeners and the underlying TCP socket."""
        if self._closed:
            return
        self._closed = True

        # Close all per-type send channels so their DemultiplexedListeners see EOF.
        for send_ch in list(self._send_channels.values()):
            send_ch.close()
        self._send_channels.clear()

        # Cancel the background nursery (stops trio.serve_tcp).
        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()

        if self._started.is_set():
            await self._stopped.wait()

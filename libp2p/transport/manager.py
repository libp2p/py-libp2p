"""
TransportManager — routes dial/listen operations to the correct transport.

Modelled after go-libp2p's transport manager in
``go-libp2p/p2p/net/swarm/swarm_transport.go``.

Usage::

    from libp2p.transport.manager import TransportManager
    from libp2p.transport.tcp.tcp import TCP
    from libp2p.transport.quic.transport import QUICTransport
    from multiaddr import Multiaddr

    mgr = TransportManager()
    mgr.add_transport(TCP())
    mgr.add_transport(QUICTransport(private_key))

    transport = mgr.transport_for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/4001"))
    # -> TCP instance

    transport = mgr.transport_for_dialing(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
    # -> QUICTransport instance

Port sharing (TCP + WebSocket on the same port)::

    from libp2p.transport.cmux import PortDemultiplexer, DemultiplexedConnType

    port_demux = PortDemultiplexer("0.0.0.0", 4001)
    mgr = TransportManager(port_demux=port_demux)

    mgr.add_transport(TCP())
    mgr.add_transport(WebsocketTransport(...))

    # TransportManager calls add_listen_addr() per multiaddr.
    # add_listen_addr() detects TCP-based addrs and delegates to PortDemultiplexer so
    # both transports share the same OS socket.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener, ITransport
from libp2p.custom_types import THandler

if TYPE_CHECKING:
    import trio

    from libp2p.transport.cmux import PortDemultiplexer

logger = logging.getLogger(__name__)


class TransportManager:
    """
    Maintains an ordered list of :class:`~libp2p.abc.ITransport` instances and
    provides routing helpers used by the :class:`~libp2p.network.swarm.Swarm`.

    Transports are checked in the order they were added. For dialing, the
    first transport whose :meth:`~libp2p.abc.ITransport.can_dial` returns
    ``True`` is selected. For listening, the same logic applies via
    :meth:`~libp2p.abc.ITransport.can_listen`.

    This is the Python equivalent of go-libp2p's ``Swarm.TransportForDialing``
    / ``Swarm.TransportForListening`` pair.

    :param port_demux: Optional :class:`~libp2p.transport.cmux.PortDemultiplexer` for
        sharing a single TCP port between multiple transports (TCP + WS).
        Mirrors the ``sharedTCP *tcpreuse.PortDemultiplexer`` parameter passed to
        ``NewTCPTransport`` / ``websocket.New`` in go-libp2p.
    """

    def __init__(
        self,
        port_demux: PortDemultiplexer | None = None,
        port_demuxers: dict[tuple[str, int], PortDemultiplexer] | None = None,
    ) -> None:
        self._transports: list[ITransport] = []
        # Shared PortDemultiplexer for TCP port reuse (optional).
        if port_demuxers is not None:
            self._port_demuxers = port_demuxers
        elif port_demux is not None:
            self._port_demuxers = {(port_demux.host, port_demux.port): port_demux}
        else:
            self._port_demuxers = {}

        self._port_demux: PortDemultiplexer | None = (
            next(iter(self._port_demuxers.values()), None)
            if self._port_demuxers
            else None
        )
        # Tracks per-(host, port) listeners for non-PortDemultiplexer paths.
        self._listeners: dict[tuple[str, int], IListener] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def add_transport(self, transport: ITransport) -> None:
        """
        Append a transport to the routing list.

        :param transport: A transport instance implementing
            :class:`~libp2p.abc.ITransport`.
        """
        self._transports.append(transport)

        # Re-sort by listen_order() to match go-libp2p's ListenOrder priority.
        # Transports without listen_order() default to priority 0 (highest).
        self._transports.sort(
            key=lambda t: getattr(t, "listen_order", lambda: 0)()
        )

        logger.debug(
            "TransportManager: registered %s (protocols=%s, listen_order=%d)",
            type(transport).__name__,
            getattr(transport, "protocols", lambda: "<unknown>")(),
            getattr(transport, "listen_order", lambda: 0)(),
        )

    def add_transports(self, transports: list[ITransport]) -> None:
        """
        Convenience helper to register multiple transports at once.

        :param transports: List of transport instances.
        """
        for t in transports:
            self.add_transport(t)

    # ── Routing ───────────────────────────────────────────────────────────────

    def transport_for_dialing(self, maddr: Multiaddr) -> ITransport | None:
        """
        Return the first registered transport that can dial *maddr*, or ``None``.

        The manager first performs a cheap pre-filter using each transport's
        :meth:`~libp2p.abc.ITransport.protocols` list (set intersection), and
        only calls :meth:`~libp2p.abc.ITransport.can_dial` when there is at
        least one protocol name overlap. This avoids unnecessary work when
        many transports are registered.

        This is the Python equivalent of go-libp2p's
        ``Swarm.TransportForDialing()``.

        :param maddr: The multiaddress to route.
        :returns: The matching transport, or ``None`` if no transport can handle
            the address.
        """
        proto_names = {p.name for p in maddr.protocols()}

        for transport in self._transports:
            # Fast pre-filter: skip if no protocol name overlap at all.
            _protocols = getattr(transport, "protocols", None)
            if _protocols is not None and not proto_names.intersection(
                set(_protocols())
            ):
                continue
            _can_dial = getattr(transport, "can_dial", None)
            if _can_dial is None or _can_dial(maddr):
                logger.debug(
                    "TransportManager.transport_for_dialing: %s => %s",
                    maddr,
                    type(transport).__name__,
                )
                return transport

        logger.warning(
            "TransportManager.transport_for_dialing: no transport found for %s "
            "(registered: %s)",
            maddr,
            [type(t).__name__ for t in self._transports],
        )
        return None

    def transport_for_listening(self, maddr: Multiaddr) -> ITransport | None:
        """
        Return the first registered transport that can listen on *maddr*, or
        ``None``.

        Uses the same two-step pre-filter logic as :meth:`transport_for_dialing`.

        This is the Python equivalent of go-libp2p's
        ``Swarm.TransportForListening()``.

        :param maddr: The multiaddress to route.
        :returns: The matching transport, or ``None`` if no transport can handle
            the address.
        """
        proto_names = {p.name for p in maddr.protocols()}

        for transport in self._transports:
            _protocols = getattr(transport, "protocols", None)
            if _protocols is not None and not proto_names.intersection(
                set(_protocols())
            ):
                continue
            _can_listen = getattr(transport, "can_listen", None)
            if _can_listen is None or _can_listen(maddr):
                logger.debug(
                    "TransportManager.transport_for_listening: %s => %s",
                    maddr,
                    type(transport).__name__,
                )
                return transport

        logger.warning(
            "TransportManager.transport_for_listening: no transport found for %s "
            "(registered: %s)",
            maddr,
            [type(t).__name__ for t in self._transports],
        )
        return None

    # ── Introspection ─────────────────────────────────────────────────────────

    def get_transports(self) -> list[ITransport]:
        """
        Return a shallow copy of the registered transports list.

        :returns: List of registered :class:`~libp2p.abc.ITransport` instances.
        """
        return list(self._transports)

    def has_transport_for(self, maddr: Multiaddr) -> bool:
        """
        Return ``True`` if any registered transport can dial *maddr*.

        :param maddr: The multiaddress to check.
        :returns: ``True`` if a matching transport exists, ``False`` otherwise.
        """
        return self.transport_for_dialing(maddr) is not None

    # ── Listening ─────────────────────────────────────────────────────────────

    def add_listen_addr(
        self, maddr: Multiaddr, conn_handler: THandler
    ) -> IListener | None:
        """
        Create and return a listener for *maddr*.

        Mirrors ``Swarm.AddListenAddr()`` from go-libp2p.

        When a :class:`~libp2p.transport.cmux.PortDemultiplexer` was supplied at
        construction **and** the address is TCP-based, the manager calls
        :meth:`~libp2p.transport.cmux.PortDemultiplexer.demultiplexed_listen` on the
        appropriate :class:`~libp2p.transport.cmux.DemultiplexedConnType` so
        that TCP and WebSocket transports can share the same OS socket.

        For non-TCP transports (e.g. QUIC) the transport's own
        :meth:`~libp2p.abc.ITransport.create_listener` is used directly.

        :param maddr: The multiaddress to listen on.
        :param conn_handler: Handler called for every accepted connection.
        :returns: An :class:`~libp2p.abc.IListener`, or ``None`` if no
            transport supports *maddr*.
        """
        transport = self.transport_for_listening(maddr)
        if transport is None:
            return None

        protocols = [p.name for p in maddr.protocols()]

        if "tcp" in protocols:
            host_val = maddr.value_for_protocol("ip4") or maddr.value_for_protocol(
                "ip6"
            )
            port_val = maddr.value_for_protocol("tcp")
            if host_val and port_val:
                key = (str(host_val), int(port_val))
                if hasattr(self, "_port_demuxers") and key in self._port_demuxers:
                    return self._add_listen_addr_shared(
                        maddr,
                        protocols,
                        transport,
                        conn_handler,
                        self._port_demuxers[key],
                    )

        # ---- Non-TCP or no PortDemultiplexer: let the transport own its listener ----
        return transport.create_listener(conn_handler)

    def _add_listen_addr_shared(
        self,
        maddr: Multiaddr,
        protocols: list[str],
        transport: ITransport,
        conn_handler: THandler,
        port_demux: PortDemultiplexer,
    ) -> IListener | None:
        """
        Wire a TCP-based transport into the shared
        :class:`~libp2p.transport.cmux.PortDemultiplexer`.

        Determines the correct :class:`~libp2p.transport.cmux.DemultiplexedConnType`
        for *transport*, registers a
        :class:`~libp2p.transport.cmux.DemultiplexedListener`, and wires
        *conn_handler* into the listener so that
        :meth:`~libp2p.transport.cmux.DemultiplexedListener.listen` starts
        the drain task automatically.

        :returns: The :class:`~libp2p.transport.cmux.DemultiplexedListener`,
            or ``None`` on failure.
        """
        from libp2p.transport.cmux import DemultiplexedConnType

        # Determine connection type for this transport.
        if "ws" in protocols or "wss" in protocols:
            is_secure = "wss" in protocols
            if is_secure:
                conn_type = DemultiplexedConnType.TLS
            else:
                conn_type = DemultiplexedConnType.HTTP

            from trio_websocket import (  # type: ignore
                wrap_server_stream,
            )

            from libp2p.transport.websocket.connection import P2PWebSocketConnection

            async def ws_wrapped_handler(stream: trio.abc.Stream) -> None:
                try:
                    async with trio.open_nursery() as ws_nursery:
                        # Max message size defaults to 32MB to match WebsocketTransport
                        request = await wrap_server_stream(
                            ws_nursery, stream, max_message_size=32 * 1024 * 1024
                        )
                        ws = await request.accept()
                        conn = P2PWebSocketConnection(
                            ws,
                            is_secure=is_secure,
                            max_buffered_amount=4 * 1024 * 1024,
                        )
                        await conn_handler(conn)
                except Exception as exc:
                    logger.error(
                        "WS upgrade failed on shared port: %s, cause: %s",
                        exc,
                        getattr(exc, "__cause__", None),
                        exc_info=True,
                    )

            if conn_type in port_demux._send_channels:
                logger.debug(
                    "PortDemultiplexer already has a listener for %s; reusing",
                    conn_type.name,
                )
                return port_demux._listeners.get(conn_type)

            return port_demux.demultiplexed_listen(
                maddr, conn_type, conn_handler=ws_wrapped_handler
            )

        else:
            conn_type = DemultiplexedConnType.MULTISTREAM_SELECT

            from libp2p.io.trio import TrioTCPStream

            async def tcp_wrapped_handler(stream: trio.abc.Stream) -> None:
                try:
                    tcp_stream = TrioTCPStream(stream)  # type: ignore[arg-type]
                    await conn_handler(tcp_stream)
                except Exception as exc:
                    logger.debug("TCP handler failed on shared port: %s", exc)

            # Check whether this conn_type is already registered — return the
            # existing DemultiplexedListener so the swarm can call listen() on it
            # and notify listeners without error.
            if conn_type in port_demux._send_channels:
                logger.debug(
                    "PortDemultiplexer already has a listener for %s; reusing",
                    conn_type.name,
                )
                return port_demux._listeners.get(conn_type)

            # Register and wire the handler in one step.
            return port_demux.demultiplexed_listen(
                maddr, conn_type, conn_handler=tcp_wrapped_handler
            )

    # Backwards-compatible alias.
    def listen_on(self, maddr: Multiaddr, conn_handler: THandler) -> IListener | None:
        """Deprecated alias for :meth:`add_listen_addr`."""
        return self.add_listen_addr(maddr, conn_handler)

    # ── Lifecycle helpers (called by Swarm) ───────────────────────────────────

    def set_background_nursery(self, nursery: trio.Nursery) -> None:
        """
        Pass the Swarm's background nursery to all transports that need one.

        Called once by :meth:`~libp2p.network.swarm.Swarm.run` as soon as the
        background nursery is ready. Delegates to every transport that exposes
        a ``set_background_nursery`` method (currently QUIC and WebSocket).

        :param nursery: The trio nursery to share with transports.
        """
        for transport in self._transports:
            if hasattr(transport, "set_background_nursery"):
                transport.set_background_nursery(nursery)  # type: ignore[attr-defined]
                logger.debug(
                    "TransportManager: set background nursery on %s",
                    type(transport).__name__,
                )

    def set_swarm(self, swarm: object) -> None:
        """
        Pass a reference to the Swarm to all transports that need it.

        Called once by :meth:`~libp2p.network.swarm.Swarm.run`. Needed by
        :class:`~libp2p.transport.quic.transport.QUICTransport` so it can
        call :meth:`~libp2p.network.swarm.Swarm.add_conn` for inbound
        QUIC connections.

        :param swarm: The :class:`~libp2p.network.swarm.Swarm` instance.
        """
        for transport in self._transports:
            if hasattr(transport, "set_swarm"):
                transport.set_swarm(swarm)  # type: ignore[attr-defined]
                logger.debug(
                    "TransportManager: set swarm reference on %s",
                    type(transport).__name__,
                )

    async def close_all(self) -> None:
        """
        Close all registered transports concurrently.

        Called by :meth:`~libp2p.network.swarm.Swarm.close` during teardown.
        """
        import trio

        async with trio.open_nursery() as nursery:
            for transport in self._transports:
                if hasattr(transport, "close"):
                    nursery.start_soon(transport.close)  # type: ignore[attr-defined]

        logger.debug(
            "TransportManager: closed all transports (%d total)",
            len(self._transports),
        )

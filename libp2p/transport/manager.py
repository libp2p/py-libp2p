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

    transport = mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/4001"))
    # -> TCP instance

    transport = mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
    # -> QUICTransport instance

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from multiaddr import Multiaddr

from libp2p.abc import IListener, ITransport
from libp2p.custom_types import THandler

if TYPE_CHECKING:
    import trio

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
    """

    def __init__(self) -> None:
        self._transports: list[ITransport] = []
        self._shared_tcp_listeners: dict[tuple[str, int], IListener] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def add_transport(self, transport: ITransport) -> None:
        """
        Append a transport to the routing list.

        :param transport: A transport instance implementing
            :class:`~libp2p.abc.ITransport`.
        """
        self._transports.append(transport)
        logger.debug(
            "TransportManager: registered %s (protocols=%s)",
            type(transport).__name__,
            getattr(transport, "protocols", lambda: "<unknown>")(),
        )

    def add_transports(self, transports: list[ITransport]) -> None:
        """
        Convenience helper to register multiple transports at once.

        :param transports: List of transport instances.
        """
        for t in transports:
            self.add_transport(t)

    # ── Routing ───────────────────────────────────────────────────────────────

    def for_dialing(self, maddr: Multiaddr) -> ITransport | None:
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
            # Use getattr for compat with test fakes that don't implement protocols().
            _protocols = getattr(transport, "protocols", None)
            if _protocols is not None and not proto_names.intersection(
                set(_protocols())
            ):
                continue
            _can_dial = getattr(transport, "can_dial", None)
            if _can_dial is None or _can_dial(maddr):
                logger.debug(
                    "TransportManager.for_dialing: %s => %s",
                    maddr,
                    type(transport).__name__,
                )
                return transport

        logger.warning(
            "TransportManager.for_dialing: no transport found for %s (registered: %s)",
            maddr,
            [type(t).__name__ for t in self._transports],
        )
        return None

    def for_listening(self, maddr: Multiaddr) -> ITransport | None:
        """
        Return the first registered transport that can listen on *maddr*, or
        ``None``.

        Uses the same two-step pre-filter logic as :meth:`for_dialing`.

        This is the Python equivalent of go-libp2p's
        ``Swarm.TransportForListening()``.

        :param maddr: The multiaddress to route.
        :returns: The matching transport, or ``None`` if no transport can handle
            the address.
        """
        proto_names = {p.name for p in maddr.protocols()}

        for transport in self._transports:
            # Use getattr for compat with test fakes that don't implement protocols().
            _protocols = getattr(transport, "protocols", None)
            if _protocols is not None and not proto_names.intersection(
                set(_protocols())
            ):
                continue
            _can_listen = getattr(transport, "can_listen", None)
            if _can_listen is None or _can_listen(maddr):
                logger.debug(
                    "TransportManager.for_listening: %s => %s",
                    maddr,
                    type(transport).__name__,
                )
                return transport

        logger.warning(
            "TransportManager.for_listening: no transport found for %s "
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
        return self.for_dialing(maddr) is not None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def listen_on(self, maddr: Multiaddr, conn_handler: THandler) -> IListener | None:
        """
        Creates and manages a listener for the given multiaddress.
        If a shared TCP port is required (e.g. for TCP and WS), it returns
        the shared dispatcher.
        """
        transport = self.for_listening(maddr)
        if transport is None:
            return None

        # Check if this is a TCP-based transport that can share a port
        # For py-libp2p, standard TCP and WebSocket run on TCP.
        protocols = [p.name for p in maddr.protocols()]
        if "tcp" in protocols:
            host_val = maddr.value_for_protocol("ip4") or maddr.value_for_protocol(
                "ip6"
            )
            host = str(host_val) if host_val else ""
            port_val = maddr.value_for_protocol("tcp")
            port = int(port_val) if port_val else 0
            key = (host, port)

            if "ws" in protocols or "wss" in protocols:
                is_ws = True
            else:
                is_ws = False

            # If it's TCP-based, we use the SharedTCPDispatcher
            # We lazy import it to avoid circular dependencies
            from .cmux import SharedTCPDispatcher

            if key not in self._shared_tcp_listeners:
                dispatcher = SharedTCPDispatcher(host, port)
                self._shared_tcp_listeners[key] = dispatcher
            else:
                dispatcher = cast(
                    "SharedTCPDispatcher", self._shared_tcp_listeners[key]
                )
                if not isinstance(dispatcher, SharedTCPDispatcher):
                    # Should not happen unless there's a port conflict with a
                    # non-CMUX listener
                    pass

            if isinstance(dispatcher, SharedTCPDispatcher):
                if is_ws:
                    # Provide an adapter that matches what WebSocket listener does.
                    # The WS connection handler expects a P2PWebSocketConnection,
                    # but here we have a WebSocketRequest from cmux.
                    # We need to wrap it using the same logic as WebsocketListener.
                    from .websocket.transport import WebsocketTransport

                    if isinstance(transport, WebsocketTransport):
                        # WebsocketTransport creates a WebsocketListener
                        # we can create one just to handle the connection wrapping!
                        # Or better, we can register the WS handler directly:
                        async def ws_cmux_handler(ws_request: Any) -> None:
                            ws = await ws_request.accept()
                            from .websocket.connection import P2PWebSocketConnection

                            # is_wss should be detected from maddr, simplify to
                            # False for now or detect:
                            is_secure = "wss" in protocols
                            conn = P2PWebSocketConnection(
                                ws,
                                is_secure=is_secure,
                                max_buffered_amount=32 * 1024 * 1024,
                            )
                            await conn_handler(conn)

                        dispatcher.ws_handler = ws_cmux_handler
                else:
                    dispatcher.tcp_handler = conn_handler
                return dispatcher

        # For non-TCP transports (e.g. QUIC), just let the transport create it
        return transport.create_listener(conn_handler)

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

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
import logging
from typing import Any

from multiaddr import Multiaddr

from libp2p.abc import IListener, INetConn, IRawConnection, ISecureConn, ITransport
from libp2p.peer.id import ID
from libp2p.transport.exceptions import OpenConnectionError

logger = logging.getLogger("libp2p.network.transport_manager")


class TransportManagerError(Exception):
    """Base transport manager error."""


class UnsupportedTransportError(TransportManagerError):
    """Raised when no registered transport can handle a multiaddr."""


class TransportManager:
    """
    Minimal transport manager that coordinates multiple transports for a swarm.
    """

    def __init__(self, host: Any, swarm: Any) -> None:
        self._host = host
        self._swarm = swarm
        self._transports: dict[str, ITransport] = {}
        self._listeners: list[IListener] = []
        self._event_listeners: dict[str, list[Callable[[Any], None]]] = defaultdict(
            list
        )

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def register_transport(self, name: str, transport: ITransport) -> None:
        """
        Register a transport instance. If already registered, this is a no-op.
        """
        existing = self._transports.get(name)
        if existing is transport:
            return

        if existing is not None:
            logger.debug("Replacing registered transport '%s'", name)

        if hasattr(transport, "set_host"):
            transport.set_host(self._host)  # type: ignore[attr-defined]

        self._transports[name] = transport

    def get_transport(self, name: str) -> ITransport | None:
        return self._transports.get(name)

    def register_listener(self, listener: IListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def get_listeners(self) -> Iterable[IListener]:
        return tuple(self._listeners)

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------
    def add_event_listener(self, event: str, callback: Callable[[Any], None]) -> None:
        self._event_listeners[event].append(callback)

    def remove_event_listener(
        self, event: str, callback: Callable[[Any], None]
    ) -> None:
        callbacks = self._event_listeners.get(event)
        if not callbacks:
            return
        try:
            callbacks.remove(callback)
        except ValueError:
            pass

    def emit(self, event: str, payload: Any) -> None:
        for callback in self._event_listeners.get(event, []):
            try:
                callback(payload)
            except Exception as exc:  # pragma: no cover - best effort logging
                logger.debug("TransportManager event handler error: %s", exc)

    # ------------------------------------------------------------------
    # Dial helpers
    # ------------------------------------------------------------------
    async def dial(self, maddr: Multiaddr, peer_id: ID | None = None) -> INetConn:
        """
        Dial a peer via the appropriate registered transport and upgrade the connection.
        """
        transport = self._select_transport(maddr)
        if transport is None:
            raise UnsupportedTransportError(f"No transport registered for {maddr}")

        maybe_is_started = getattr(transport, "is_started", None)
        maybe_start = getattr(transport, "start", None)

        should_start = False
        if callable(maybe_is_started):
            try:
                should_start = not bool(maybe_is_started())
            except TypeError:
                should_start = False

        if should_start and callable(maybe_start):
            try:
                start_result = maybe_start()
            except TypeError:
                logger.debug(
                    "Transport start() signature mismatch; skipping auto-start"
                )
            else:
                if isinstance(start_result, Awaitable):
                    await start_result

        # Allow transports to prepare any prerequisite signaling paths.
        if hasattr(transport, "ensure_signaling_connection"):
            await transport.ensure_signaling_connection(maddr)  # type: ignore[attr-defined]

        raw_conn = await transport.dial(maddr)
        if not isinstance(raw_conn, (IRawConnection, ISecureConn)):
            raise OpenConnectionError("Transport did not return a connection")

        target_peer = self._resolve_peer_id(maddr, peer_id)

        if isinstance(raw_conn, ISecureConn):
            secured_conn: ISecureConn = raw_conn
        else:
            secured_conn = await self._swarm.upgrader.upgrade_security(
                raw_conn, True, target_peer
            )
        muxed_conn = await self._swarm.upgrader.upgrade_connection(
            secured_conn, target_peer
        )
        swarm_conn = await self._swarm.add_conn(muxed_conn)
        return swarm_conn

    def _select_transport(self, maddr: Multiaddr) -> ITransport | None:
        # Prefer exact matches by inspecting protocols in the multiaddr.
        protocols = {proto.name for proto in maddr.protocols()}

        # Prefer WebRTC for addresses that explicitly request it.
        if "webrtc" in protocols and "webrtc" in self._transports:
            return self._transports["webrtc"]

        # Prefer circuit relay transport for p2p-circuit addresses.
        if "p2p-circuit" in protocols and "circuit-relay" in self._transports:
            return self._transports["circuit-relay"]

        # Fallback: first transport that claims it can handle the address.
        for transport in self._transports.values():
            if hasattr(transport, "can_handle") and transport.can_handle(maddr):  # type: ignore[call-arg]
                return transport

        return None

    def _resolve_peer_id(self, maddr: Multiaddr, peer_id: ID | None = None) -> ID:
        if peer_id is not None:
            return peer_id

        peer_component = maddr.value_for_protocol("p2p")
        if peer_component:
            return ID.from_base58(peer_component)

        raise TransportManagerError(
            f"Unable to determine remote peer id from multiaddr {maddr}"
        )

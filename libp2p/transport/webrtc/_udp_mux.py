"""
UdpMux: shared UDP socket dispatcher for WebRTC-Direct inbound connections.

Routes incoming datagrams to per-dial aioice.Connection instances:
  - STUN packets:  by local ufrag prefix in the USERNAME attribute (pre-ICE)
  - non-STUN data: by remote (host, port) pair (post-ICE DTLS / SCTP)

This is the foundational primitive for a spec-aligned WebRTC-Direct listener
that advertises a single fixed UDP port and demuxes concurrent inbound dials
without spinning up a new port per peer.

Validated against ``aioice`` 0.10.x. It relies on private ``aioice`` internals
(``StunProtocol``, ``Connection._protocols`` / ``_local_candidates`` /
``_local_candidates_end``) to inject a mux-backed protocol without aioice
binding its own UDP socket, so it may need updating on aioice major bumps.
Upstreaming a real ``UdpMux`` into aioice is tracked as follow-up on #1352.

Refs: libp2p/specs#715 (WebRTC-Direct v2), libp2p/py-libp2p#1352 (spike).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import socket
import struct
from typing import Protocol

try:
    from aioice.candidate import Candidate
    import aioice.ice as _ice
    import aioice.stun as _stun

    _HAS_AIOICE = True
except ImportError:
    _HAS_AIOICE = False


class _HasConnectionLost(Protocol):
    def connection_lost(self, exc: Exception | None) -> None: ...
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None: ...


logger = logging.getLogger(__name__)


class _MuxedTransport:
    """
    Fake DatagramTransport backed by the mux's real shared socket.

    Passed to aioice's StunProtocol so that aioice can send datagrams without
    ever owning its own UDP socket.  close() signals the protocol rather than
    closing the shared socket.
    """

    def __init__(
        self,
        real_transport: asyncio.DatagramTransport,
        local_addr: tuple[str, int],
        mux: UdpMux | None = None,
    ) -> None:
        self._real = real_transport
        self._local_addr = local_addr
        self._mux = mux
        # Set by UdpMux after the StunProtocol is constructed (avoids circular ref).
        self._protocol: _HasConnectionLost | None = None

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        # Anything we send to (our own connectivity checks included) will
        # answer from that address without a USERNAME, so learn the mapping
        # on the way out.
        if self._mux is not None and self._protocol is not None:
            self._mux._learn_addr((addr[0], addr[1]), self._protocol)
        self._real.sendto(data, addr)

    def close(self) -> None:
        # Let the protocol know the "transport" is gone so aioice's
        # `await protocol.close()` can complete without blocking forever.
        if self._protocol is not None:
            self._protocol.connection_lost(None)

    def get_extra_info(self, key: str, default: object = None) -> object:
        if key == "sockname":
            return self._local_addr
        return default


class UdpMux(asyncio.DatagramProtocol):
    """
    Shared UDP socket for WebRTC-Direct inbound connections.

    Create one instance per listener port via :meth:`create`, then call
    :meth:`add_ice_connection` for each inbound dial.  After ICE completes,
    call :meth:`register_addr` with the elected remote address so that
    subsequent DTLS/SCTP datagrams from that peer are dispatched correctly.

    Example::

        mux, port = await UdpMux.create("0.0.0.0", 0)

        # Observe first-contact STUN for unregistered ufrags:
        mux.set_unknown_stun_handler(on_new_dial)

        # When a new STUN BINDING REQUEST arrives for ufrag "abc":
        conn = mux.add_ice_connection("abc", "password123", host="0.0.0.0")
        for c in remote_candidates:
            await conn.add_remote_candidate(c)
        await conn.add_remote_candidate(None)  # end-of-candidates
        await conn.connect()                   # do NOT call gather_candidates()

        # The peer's address is learned from its STUN checks; register_addr()
        # can add more (e.g. the nominated pair's remote address).

        # Teardown (also drops the addresses learned for "abc"):
        mux.unregister("abc")
        await mux.close()

    To run a full aiortc ``RTCPeerConnection`` over a muxed connection use
    :func:`libp2p.transport.webrtc._aiortc_helpers.attach_muxed_connection`.
    """

    # Bound on addresses learned per connection (a real peer has a handful
    # of candidates; anything beyond that is noise or an attack).
    _MAX_ADDRS_PER_PROTOCOL = 16

    def __init__(self) -> None:
        self._transport: asyncio.DatagramTransport | None = None
        self._local_addr: tuple[str, int] | None = None
        # ufrag -> StunProtocol (pre-ICE STUN dispatch)
        self._by_ufrag: dict[str, _HasConnectionLost] = {}
        # (host, port) -> StunProtocol (post-ICE DTLS/SCTP dispatch)
        self._by_addr: dict[tuple[str, int], _HasConnectionLost] = {}
        # id(protocol) -> number of _by_addr entries pointing at it
        self._addr_count: dict[int, int] = {}
        # Called with the full USERNAME for a BINDING REQUEST whose local ufrag
        # is not registered (see set_unknown_stun_handler); lets a listener
        # observe first-contact dials.
        self._unknown_stun_handler: (
            Callable[[str, bytes, tuple[str, int]], None] | None
        ) = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, host: str, port: int) -> tuple[UdpMux, int]:
        """
        Bind a shared UDP socket on *host*:*port* (use ``port=0`` for OS choice).
        Returns ``(mux, bound_port)``.
        """
        loop = asyncio.get_running_loop()
        mux = cls()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: mux, local_addr=(host, port)
        )
        # connection_made is called synchronously inside create_datagram_endpoint,
        # so _transport and _local_addr are set by the time we return.
        assert mux._local_addr is not None
        return mux, mux._local_addr[1]

    # ------------------------------------------------------------------
    # asyncio.DatagramProtocol
    # ------------------------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]
        addr = transport.get_extra_info("sockname")
        self._local_addr = (addr[0], addr[1])
        # Windows reports an ICMP port-unreachable for a datagram we sent (e.g.
        # a keepalive to a peer that just closed) as WSAECONNRESET on the *next
        # recv* of this shared socket, and the proactor loop does not re-arm
        # reading after error_received - the mux would go deaf for every other
        # peer. SIO_UDP_CONNRESET=False disables that behaviour. No-op elsewhere.
        sio = getattr(socket, "SIO_UDP_CONNRESET", None)
        sock = transport.get_extra_info("socket")
        if sio is not None and sock is not None:
            try:
                sock.ioctl(sio, False)
            except OSError:
                logger.debug("UdpMux: SIO_UDP_CONNRESET not applied", exc_info=True)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        norm: tuple[str, int] = (addr[0], addr[1])
        try:
            msg = _stun.parse_message(data)
        except ValueError:
            # Non-STUN (DTLS handshake, SCTP frames after ICE): route by addr.
            # aioice's StunProtocol re-parses, hits the same ValueError and
            # forwards the bytes to the connection's data path.
            self._route_by_addr(data, norm, stun_shaped=False)
            return
        except struct.error:
            # STUN-shaped but malformed: aioice parses attributes with
            # struct.unpack, which raises struct.error (NOT a ValueError
            # subclass) on a short fixed-width attribute. StunProtocol only
            # catches ValueError, so handing this to protocol.datagram_received
            # would let the same struct.error escape the loop callback. Deliver
            # straight to the ICE connection's data path instead (DTLS/SCTP
            # discard garbage) so a crafted packet can neither raise here nor
            # log-flood.
            self._route_by_addr(data, norm, stun_shaped=True)
            return

        # Only BINDING REQUESTs carry USERNAME (``local:remote``); responses
        # and indications must be routed by address.
        username: str = msg.attributes.get("USERNAME", "")
        ufrag = username.split(":")[0]
        protocol = self._by_ufrag.get(ufrag) if ufrag else None
        if protocol is not None:
            # Learn the peer address from its STUN checks so post-ICE DTLS/SCTP
            # from that address routes even if it races ahead of our own ICE
            # "completed" transition (the controlling dialer sends its DTLS
            # ClientHello as soon as *it* nominates). Same approach as pion's
            # UDPMux. A spoofed STUN with a known ufrag can only cause the
            # attacker's bytes to be fed to that connection's DTLS, which
            # discards them.
            self._learn_addr(norm, protocol)
            protocol.datagram_received(data, norm)
            return
        is_first_contact = (
            ufrag != ""
            and msg.message_class == _stun.Class.REQUEST
            and msg.message_method == _stun.Method.BINDING
        )
        if is_first_contact and self._unknown_stun_handler is not None:
            # First contact: an inbound BINDING REQUEST for an unregistered
            # ufrag. A WebRTC-Direct listener registers a handler to create the
            # connection (add_ice_connection) and replay this datagram.
            self._unknown_stun_handler(username, data, norm)
            return
        protocol = self._by_addr.get(norm)
        if protocol is not None:
            protocol.datagram_received(data, norm)
            return
        logger.debug("UdpMux: no handler for STUN ufrag %r from %s", ufrag, norm)

    def _learn_addr(self, addr: tuple[str, int], protocol: _HasConnectionLost) -> None:
        """
        Map *addr* -> *protocol* for non-STUN routing.

        Latest wins (like pion's UDPMux): a peer that redials from the same
        (ip, port) with a new ufrag must reach its *new* connection, not the
        stale one still being torn down. Learned addresses are capped per
        protocol because inbound STUN is unauthenticated at this layer — a
        flood of requests carrying a live ufrag from many source ports must
        not grow the table without bound.
        """
        current = self._by_addr.get(addr)
        if current is protocol:
            return
        n = self._addr_count.get(id(protocol), 0)
        if n >= self._MAX_ADDRS_PER_PROTOCOL:
            return
        if current is not None:
            self._addr_count[id(current)] = self._addr_count.get(id(current), 1) - 1
        self._by_addr[addr] = protocol
        self._addr_count[id(protocol)] = n + 1

    def _route_by_addr(
        self, data: bytes, norm: tuple[str, int], *, stun_shaped: bool
    ) -> None:
        protocol = self._by_addr.get(norm)
        if protocol is None:
            logger.debug("UdpMux: no handler for non-STUN datagram from %s", norm)
            return
        if not stun_shaped:
            protocol.datagram_received(data, norm)
            return
        # Bypass StunProtocol's parser (see datagram_received); StunProtocol
        # exposes the owning aioice.Connection as ``receiver``.
        receiver = getattr(protocol, "receiver", None)
        if receiver is not None and hasattr(receiver, "data_received"):
            receiver.data_received(data, 1)
        else:
            logger.debug("UdpMux: dropped malformed STUN-shaped datagram from %s", norm)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UdpMux socket error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        logger.debug("UdpMux connection lost: %s", exc)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, ufrag: str, protocol: _HasConnectionLost) -> None:
        """Route STUN packets with local ufrag *ufrag* to *protocol*."""
        self._by_ufrag[ufrag] = protocol

    def register_addr(
        self, addr: tuple[str, int], protocol: _HasConnectionLost
    ) -> None:
        """Route non-STUN packets from *addr* to *protocol* (call after ICE)."""
        current = self._by_addr.get(addr)
        if current is not None and current is not protocol:
            self._addr_count[id(current)] = self._addr_count.get(id(current), 1) - 1
        if current is not protocol:
            self._addr_count[id(protocol)] = self._addr_count.get(id(protocol), 0) + 1
        self._by_addr[addr] = protocol

    def unregister(self, ufrag: str) -> None:
        """Drop *ufrag* and every address learned/registered for its protocol."""
        protocol = self._by_ufrag.pop(ufrag, None)
        if protocol is None:
            return
        for addr in [a for a, p in self._by_addr.items() if p is protocol]:
            del self._by_addr[addr]
        self._addr_count.pop(id(protocol), None)

    def unregister_addr(self, addr: tuple[str, int]) -> None:
        protocol = self._by_addr.pop(addr, None)
        if protocol is not None:
            self._addr_count[id(protocol)] = self._addr_count.get(id(protocol), 1) - 1

    def set_unknown_stun_handler(
        self, handler: Callable[[str, bytes, tuple[str, int]], None] | None
    ) -> None:
        """
        Register a callback for STUN packets whose ufrag is not yet registered.

        The callback receives ``(username, data, addr)`` where ``username`` is
        the full STUN ``USERNAME`` (``local_ufrag:remote_ufrag``) of an inbound
        BINDING REQUEST whose local ufrag is unregistered. For WebRTC-Direct
        this is how a listener observes the *first* packet from a new dialer —
        it can create and register the connection via
        :meth:`add_ice_connection` and replay ``data``. Called from the asyncio
        event-loop thread; keep it non-blocking (e.g. hand off to a queue).
        Pass ``None`` to clear.
        """
        self._unknown_stun_handler = handler

    # ------------------------------------------------------------------
    # Connection factory
    # ------------------------------------------------------------------

    def add_ice_connection(
        self,
        local_username: str,
        local_password: str,
        *,
        host: str,
    ) -> _ice.Connection:
        """
        Create an ``aioice.Connection`` backed by this mux (no own UDP socket).

        The connection is pre-registered for *local_username* so that inbound
        STUN connectivity checks are dispatched correctly before the caller
        has a chance to set remote candidates. The single host candidate on the
        shared port is injected as the connection's local candidate, so the
        caller must **not** call ``conn.gather_candidates()`` — doing so binds
        additional UDP sockets and defeats the shared-port design.

        The caller must:
        1. For each of the dialer's candidates, ``await conn.add_remote_candidate(c)``,
           then ``await conn.add_remote_candidate(None)`` to signal end-of-candidates.
        2. Await ``conn.connect()`` to complete ICE negotiation.
        3. (Optional) call ``register_addr(remote_addr, conn._protocols[0])``
           once ICE selects a candidate pair; the mux already learns the peer's
           address from its STUN checks.
        4. Call ``unregister(local_username)`` on teardown.
        """
        if not _HAS_AIOICE:
            raise RuntimeError("aioice is required (install py-libp2p[webrtc])")
        assert self._transport is not None, "UdpMux not yet bound (call create() first)"
        assert self._local_addr is not None

        conn = _ice.Connection(
            ice_controlling=False,
            local_username=local_username,
            local_password=local_password,
        )

        muxed_transport = _MuxedTransport(self._transport, self._local_addr, self)
        protocol = _ice.StunProtocol(conn)
        # Wire the fake transport so aioice can send responses.
        protocol.transport = muxed_transport  # type: ignore[assignment]
        # Back-reference so _MuxedTransport.close() can resolve protocol.close().
        # aioice types connection_lost(exc: Exception) but asyncio protocol is Optional.
        muxed_transport._protocol = protocol  # type: ignore[assignment]

        local_candidate = Candidate(
            foundation=_ice.candidate_foundation("host", "udp", host),
            component=1,
            transport="udp",
            priority=_ice.candidate_priority(1, "host"),
            host=host,
            port=self._local_addr[1],
            type="host",
        )
        protocol.local_candidate = local_candidate

        # Inject into aioice's internal protocol list, bypassing gather_candidates
        # (which would bind extra UDP sockets). Mark gathering both *started*
        # and *complete*: ``_end`` lets Connection.connect() proceed instead of
        # raising "Local candidates gathering was not performed"; ``_start``
        # makes a later gather_candidates() call — which aiortc's
        # RTCIceGatherer.gather() issues unconditionally from
        # setLocalDescription — a no-op instead of binding fresh sockets and
        # appending their candidates to ours.
        # Guard the private-slot writes: a renamed/dropped aioice attribute
        # would otherwise be a silent no-op (a new attribute aioice never
        # reads) and only fail far downstream.
        for attr in (
            "_protocols",
            "_local_candidates",
            "_local_candidates_start",
            "_local_candidates_end",
        ):
            assert hasattr(conn, attr), f"aioice Connection has no {attr!r}"
        conn._protocols.append(protocol)
        conn._local_candidates = [local_candidate]
        conn._local_candidates_start = True
        conn._local_candidates_end = True
        self.register(local_username, protocol)  # type: ignore[arg-type]
        return conn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def local_addr(self) -> tuple[str, int] | None:
        return self._local_addr

    async def close(self) -> None:
        """Close the shared UDP socket and drop all dispatch registrations."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        # Clear routing tables so a datagram racing with close() can't be
        # dispatched to a half-torn-down protocol.
        self._by_ufrag.clear()
        self._by_addr.clear()
        self._addr_count.clear()
        self._unknown_stun_handler = None

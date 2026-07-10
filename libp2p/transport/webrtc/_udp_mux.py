"""
UdpMux: shared UDP socket dispatcher for WebRTC-Direct inbound connections.

Routes incoming datagrams to per-dial aioice.Connection instances:
  - STUN packets:  by local ufrag prefix in the USERNAME attribute (pre-ICE)
  - non-STUN data: by remote (host, port) pair (post-ICE DTLS / SCTP)

This is the foundational primitive for a spec-aligned WebRTC-Direct listener
that advertises a single fixed UDP port and demuxes concurrent inbound dials
without spinning up a new port per peer.

Refs: libp2p/specs#715 (WebRTC-Direct v2), libp2p/py-libp2p#1352 (spike).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol

try:
    import aioice.ice as _ice
    import aioice.stun as _stun
    from aioice.candidate import Candidate

    _HAS_AIOICE = True
except ImportError:
    _HAS_AIOICE = False


class _HasConnectionLost(Protocol):
    def connection_lost(self, exc: Optional[Exception]) -> None: ...
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
    ) -> None:
        self._real = real_transport
        self._local_addr = local_addr
        # Set by UdpMux after the StunProtocol is constructed (avoids circular ref).
        self._protocol: Optional[_HasConnectionLost] = None

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
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

        # When a new STUN BINDING REQUEST arrives for ufrag "abc":
        conn = mux.add_ice_connection("abc", "password123", host="0.0.0.0")
        # ... feed candidates, call conn.connect(), await ICE completion ...

        # After ICE selects a candidate pair:
        mux.register_addr(("203.0.113.5", 54321), conn._protocols[0])

        # Teardown:
        mux.unregister("abc")
        mux.unregister_addr(("203.0.113.5", 54321))
        await mux.close()
    """

    def __init__(self) -> None:
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._local_addr: Optional[tuple[str, int]] = None
        # ufrag -> StunProtocol (pre-ICE STUN dispatch)
        self._by_ufrag: dict[str, _HasConnectionLost] = {}
        # (host, port) -> StunProtocol (post-ICE DTLS/SCTP dispatch)
        self._by_addr: dict[tuple[str, int], _HasConnectionLost] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, host: str, port: int) -> tuple["UdpMux", int]:
        """
        Bind a shared UDP socket on *host*:*port* (use ``port=0`` for OS choice).
        Returns ``(mux, bound_port)``.
        """
        loop = asyncio.get_event_loop()
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

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        norm: tuple[str, int] = (addr[0], addr[1])
        try:
            msg = _stun.parse_message(data)
            username: str = msg.attributes.get("USERNAME", "")
            ufrag = username.split(":")[0]
            protocol = self._by_ufrag.get(ufrag)
            if protocol is not None:
                protocol.datagram_received(data, norm)
                return
            logger.debug("UdpMux: no handler for ufrag %r from %s", ufrag, norm)
        except ValueError:
            # Non-STUN (DTLS handshake, SCTP frames after ICE): route by addr.
            protocol = self._by_addr.get(norm)
            if protocol is not None:
                protocol.datagram_received(data, norm)
                return
            logger.debug("UdpMux: no handler for non-STUN datagram from %s", norm)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UdpMux socket error: %s", exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        logger.debug("UdpMux connection lost: %s", exc)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, ufrag: str, protocol: _HasConnectionLost) -> None:
        """Route STUN packets with local ufrag *ufrag* to *protocol*."""
        self._by_ufrag[ufrag] = protocol

    def register_addr(self, addr: tuple[str, int], protocol: _HasConnectionLost) -> None:
        """Route non-STUN packets from *addr* to *protocol* (call after ICE)."""
        self._by_addr[addr] = protocol

    def unregister(self, ufrag: str) -> None:
        self._by_ufrag.pop(ufrag, None)

    def unregister_addr(self, addr: tuple[str, int]) -> None:
        self._by_addr.pop(addr, None)

    # ------------------------------------------------------------------
    # Connection factory
    # ------------------------------------------------------------------

    def add_ice_connection(
        self,
        local_username: str,
        local_password: str,
        *,
        host: str,
    ) -> "_ice.Connection":
        """
        Create an ``aioice.Connection`` backed by this mux (no own UDP socket).

        The connection is pre-registered for *local_username* so that inbound
        STUN connectivity checks are dispatched correctly before the caller
        has a chance to set remote candidates.

        The caller must:
        1. Call ``conn.set_remote_candidates([...])`` with the dialer's candidates.
        2. Await ``conn.connect()`` to complete ICE negotiation.
        3. Call ``register_addr(remote_addr, conn._protocols[0])`` once ICE
           selects a candidate pair so that post-ICE DTLS/SCTP is routed.
        4. Call ``unregister(local_username)`` and
           ``unregister_addr(remote_addr)`` on teardown.
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

        muxed_transport = _MuxedTransport(self._transport, self._local_addr)
        protocol = _ice.StunProtocol(conn)
        # Wire the fake transport so aioice can send responses.
        protocol.transport = muxed_transport  # type: ignore[assignment]
        # Back-reference so _MuxedTransport.close() can resolve protocol.close().
        # aioice types connection_lost(exc: Exception) but asyncio protocol is Optional.
        muxed_transport._protocol = protocol  # type: ignore[assignment]

        protocol.local_candidate = Candidate(
            foundation=_ice.candidate_foundation("host", "udp", host),
            component=1,
            transport="udp",
            priority=_ice.candidate_priority(1, "host"),
            host=host,
            port=self._local_addr[1],
            type="host",
        )

        # Inject into aioice's internal protocol list, bypassing _gather_candidates.
        conn._protocols.append(protocol)
        self.register(local_username, protocol)  # type: ignore[arg-type]
        return conn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def local_addr(self) -> Optional[tuple[str, int]]:
        return self._local_addr

    async def close(self) -> None:
        """Close the shared UDP socket."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

"""
WebRTC Direct transport.

Implements :class:`ITransport` for the ``/webrtc-direct`` multiaddr scheme.
The server publishes its DTLS certificate hash in the multiaddr; the client
constructs an SDP locally — no signaling exchange is needed.

This transport provides native stream multiplexing (data channels), so it
sets ``provides_native_muxing = True`` and the swarm skips the
TransportUpgrader.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multiaddr import Multiaddr
import trio

from libp2p.abc import ITransport
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from ._asyncio_bridge import AsyncioBridge
from .certificate import WebRTCCertificate
from .config import WebRTCTransportConfig
from .connection import WebRTCConnection
from .exceptions import WebRTCConnectionError
from .listener import WebRTCDirectListener
from .multiaddr_utils import (
    is_webrtc_direct_multiaddr,
    parse_webrtc_direct_multiaddr,
)
from .sdp import SDPBuilder

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebRTCDirectTransport(ITransport):
    """
    WebRTC Direct transport (``/webrtc-direct``).

    Usage::

        transport = WebRTCDirectTransport(private_key=my_key)
        # Dial a remote peer
        conn = await transport.dial(
            Multiaddr("/ip4/1.2.3.4/udp/9090/webrtc-direct/certhash/uEi.../p2p/12D3...")
        )
        # Or create a listener
        listener = transport.create_listener(handler)
        await listener.listen(Multiaddr("/ip4/0.0.0.0/udp/9090/webrtc-direct"), nursery)
    """

    # The swarm checks this to skip the TransportUpgrader
    provides_native_muxing: bool = True

    def __init__(
        self,
        private_key: PrivateKey,
        config: WebRTCTransportConfig | None = None,
    ) -> None:
        self._private_key = private_key
        self._config = config or WebRTCTransportConfig()
        self._certificate = self._config.get_or_generate_certificate()
        self._bridge: AsyncioBridge | None = None
        self._bridge_lock = trio.Lock()
        self._local_peer_id = ID.from_pubkey(private_key.get_public_key())
        self._sdp_builder = SDPBuilder(certificate=self._certificate)

    async def _ensure_bridge(self) -> AsyncioBridge:
        """Start the asyncio bridge on first use (concurrency-safe)."""
        if self._bridge is not None:
            return self._bridge
        async with self._bridge_lock:
            if self._bridge is None:
                self._bridge = AsyncioBridge()
                await self._bridge.start()
        return self._bridge

    async def dial(self, maddr: Multiaddr) -> WebRTCConnection:
        """
        Dial a remote peer over WebRTC Direct.

        :param maddr: A ``/webrtc-direct`` multiaddr with certhash.
        :returns: A :class:`WebRTCConnection` (implements both
            ``IRawConnection`` and ``IMuxedConn``).
        :raises NotImplementedError: The aiortc integration is not yet
            wired up.  Returning a bare :class:`WebRTCConnection` at this
            stage would make the swarm treat the peer as connected while
            streams silently drop data.  The full dial sequence
            (RTCPeerConnection creation, ICE/DTLS, Noise handshake,
            ``conn.start()``) lands in a follow-up PR.
        :raises WebRTCConnectionError: If the multiaddr is malformed.
        """
        # Validate the multiaddr even though we can't complete the dial, so
        # callers get a consistent error shape once the transport is live.
        if not is_webrtc_direct_multiaddr(maddr):
            raise WebRTCConnectionError(f"Not a WebRTC Direct multiaddr: {maddr}")
        _host, _port, certhash, _peer_id_str = parse_webrtc_direct_multiaddr(maddr)
        if not certhash:
            raise WebRTCConnectionError(
                f"WebRTC Direct multiaddr missing certhash: {maddr}"
            )

        # The full dial sequence is:
        # 1. Create RTCPeerConnection via bridge
        # 2. Set local SDP offer
        # 3. Construct remote SDP from multiaddr certhash
        # 4. Wait for ICE connection
        # 5. Perform Noise XX handshake over data channel 0
        # 6. Verify remote peer identity
        # 7. Call conn.start()
        raise NotImplementedError(
            "WebRTC Direct dial is not yet wired to aiortc. "
            "This transport is registered for interface-compliance and "
            "test coverage only; see PR #1309 for scope."
        )

    def create_listener(self, handler_function: THandler) -> WebRTCDirectListener:
        """
        Create a WebRTC Direct listener.

        :param handler_function: Called with each new inbound connection.
        :returns: A :class:`WebRTCDirectListener`.
        """
        return WebRTCDirectListener(
            handler_function=handler_function,
            private_key=self._private_key,
            certificate=self._certificate,
            config=self._config,
            bridge_factory=self._ensure_bridge,
            local_peer_id=self._local_peer_id,
        )

    async def close(self) -> None:
        """
        Shut down the transport and its asyncio bridge.

        Acquires the same lock as :meth:`_ensure_bridge` so a concurrent
        dial cannot resurrect the bridge mid-shutdown.
        """
        async with self._bridge_lock:
            if self._bridge is not None:
                await self._bridge.stop()
                self._bridge = None

    @property
    def certificate(self) -> WebRTCCertificate:
        """The local DTLS certificate."""
        return self._certificate

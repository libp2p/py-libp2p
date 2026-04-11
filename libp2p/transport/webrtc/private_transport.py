"""
WebRTC private-to-private transport.

Implements :class:`ITransport` for the ``/webrtc`` multiaddr scheme where
both peers are behind NAT.  Uses Circuit Relay v2 for the signaling channel,
then upgrades to a direct WebRTC data-channel connection.

Multiaddr format::

    <relay-multiaddr>/p2p-circuit/webrtc/p2p/<remote-peer-id>

The dial sequence:

1. Open a relayed connection to the remote peer.
2. Open a stream with ``/webrtc-signaling/0.0.1``.
3. Exchange SDP offer/answer via :class:`SignalingSession`.
4. Trickle ICE candidates with bilateral ``ICE_DONE`` (specs#585 fix).
5. Wait for direct WebRTC connection to establish.
6. Perform Noise XX handshake over data channel 0.
7. Return :class:`WebRTCConnection`.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import trio
from multiaddr import Multiaddr

from libp2p.abc import ITransport
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from ._asyncio_bridge import AsyncioBridge
from .certificate import WebRTCCertificate
from .config import WebRTCTransportConfig
from .connection import WebRTCConnection
from .constants import WEBRTC_SIGNALING_PROTOCOL_ID
from .exceptions import WebRTCConnectionError, WebRTCSignalingError
from .multiaddr_utils import is_webrtc_multiaddr
from .private_listener import WebRTCPrivateListener
from .sdp import SDPBuilder

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebRTCPrivateTransport(ITransport):
    """
    WebRTC transport for private-to-private connections (``/webrtc``).

    Both peers are behind NAT.  Signaling happens over a Circuit Relay v2
    stream, then a direct WebRTC connection is established.

    Usage::

        transport = WebRTCPrivateTransport(private_key=my_key, host=my_host)
        conn = await transport.dial(
            Multiaddr("/ip4/.../udp/.../quic-v1/p2p/<relay>/p2p-circuit/webrtc/p2p/<remote>")
        )
    """

    provides_native_muxing: bool = True

    def __init__(
        self,
        private_key: PrivateKey,
        host: object | None = None,
        config: WebRTCTransportConfig | None = None,
    ) -> None:
        self._private_key = private_key
        self._host = host  # IHost — typed as object to avoid circular import
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
        Dial a remote peer over WebRTC via a relay.

        :param maddr: A ``/p2p-circuit/webrtc/p2p/<peer-id>`` multiaddr.
        :returns: A :class:`WebRTCConnection`.
        :raises WebRTCConnectionError: If the connection fails.
        """
        if not is_webrtc_multiaddr(maddr):
            raise WebRTCConnectionError(
                f"Not a relay-based WebRTC multiaddr: {maddr}"
            )

        bridge = await self._ensure_bridge()
        logger.info("Dialing WebRTC (private-to-private) via %s", maddr)

        # Extract the remote peer ID from the multiaddr
        maddr_str = str(maddr)
        parts = maddr_str.split("/p2p/")
        if len(parts) < 2:
            raise WebRTCConnectionError(
                f"Cannot extract remote peer ID from multiaddr: {maddr}"
            )
        remote_peer_id_str = parts[-1].split("/")[0]
        remote_peer_id = ID.from_base58(remote_peer_id_str)

        conn = WebRTCConnection(
            peer_id=remote_peer_id,
            bridge=bridge,
            is_initiator=True,
            config=self._config,
            remote_addrs=[maddr],
        )

        # NOTE: Full dial sequence (relay connection → signaling → ICE → Noise)
        # is wired up when aiortc integration is complete.  The sequence:
        #
        # 1. host.new_stream(relay_peer, [RELAY_PROTOCOL])
        # 2. Open /webrtc-signaling/0.0.1 stream on relayed connection
        # 3. SignalingSession.send_offer()
        # 4. SignalingSession.receive_answer()
        # 5. Exchange ICE candidates with bilateral ICE_DONE
        # 6. Create RTCPeerConnection, wait for ICE connected
        # 7. Noise XX handshake over data channel 0
        # 8. conn.start()

        return conn

    def create_listener(self, handler_function: THandler) -> WebRTCPrivateListener:
        """
        Create a listener for incoming WebRTC signaling.

        The listener registers a stream handler for
        ``/webrtc-signaling/0.0.1`` on the host so that remote peers
        can initiate WebRTC connections through a relay.

        :param handler_function: Called with each new inbound connection.
        :returns: A :class:`WebRTCPrivateListener`.
        """
        return WebRTCPrivateListener(
            handler_function=handler_function,
            private_key=self._private_key,
            certificate=self._certificate,
            config=self._config,
            bridge_factory=self._ensure_bridge,
            local_peer_id=self._local_peer_id,
            host=self._host,
        )

    async def close(self) -> None:
        """Shut down the transport and its asyncio bridge."""
        if self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None

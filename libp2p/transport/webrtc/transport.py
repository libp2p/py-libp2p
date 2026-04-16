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


async def _async_noop(value: object) -> object:
    """Wrap a synchronous value as an awaitable for bridge.run_coro()."""
    return value


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
        :raises WebRTCConnectionError: If the connection fails.
        """
        if not is_webrtc_direct_multiaddr(maddr):
            raise WebRTCConnectionError(f"Not a WebRTC Direct multiaddr: {maddr}")
        host, port, certhash, peer_id_str = parse_webrtc_direct_multiaddr(maddr)
        if not certhash:
            raise WebRTCConnectionError(
                f"WebRTC Direct multiaddr missing certhash: {maddr}"
            )

        bridge = await self._ensure_bridge()
        logger.info("Dialing WebRTC Direct %s:%d", host, port)

        remote_peer_id: ID | None = None
        if peer_id_str:
            remote_peer_id = ID.from_base58(peer_id_str)

        # All aiortc calls go through the bridge (asyncio thread).
        from ._aiortc_helpers import (
            create_noise_channel,
            create_peer_connection,
            get_remote_fingerprint,
            make_noise_channel_callbacks,
            post_sdp,
            wait_for_connected,
            wire_pc_to_connection,
        )
        from .certificate import fingerprint_from_multibase
        from .noise_handshake import DataChannelReadWriter, perform_noise_handshake

        rtc_cert = getattr(self._certificate, "_rtc_certificate", None)
        if rtc_cert is None:
            raise WebRTCConnectionError(
                "WebRTC certificate was not generated via aiortc. "
                "Ensure aiortc is installed and config uses from_aiortc()."
            )

        try:
            # 1. Create RTCPeerConnection + Noise channel
            pc = await bridge.run_coro(_async_noop(create_peer_connection(rtc_cert)))
            noise_ch = await bridge.run_coro(create_noise_channel(pc))
            noise_send, noise_recv, _ = await bridge.run_coro(
                _async_noop(make_noise_channel_callbacks(noise_ch))
            )

            # 2. Create offer, set local description
            offer = await bridge.run_coro(pc.createOffer())
            await bridge.run_coro(pc.setLocalDescription(offer))

            # 3. Exchange SDP via HTTP POST to the listener
            answer_sdp = await bridge.run_coro(
                post_sdp(host, port, pc.localDescription.sdp)
            )

            # 4. Set remote description
            from aiortc import RTCSessionDescription

            answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
            await bridge.run_coro(pc.setRemoteDescription(answer))

            # 5. Wait for ICE connection
            await bridge.run_coro(wait_for_connected(pc))

            # 6. Verify remote DTLS fingerprint
            expected_fp = fingerprint_from_multibase(certhash)
            remote_fp = await bridge.run_coro(_async_noop(get_remote_fingerprint(pc)))
            if remote_fp != expected_fp:
                await bridge.run_coro(pc.close())
                raise WebRTCConnectionError(
                    "Remote DTLS fingerprint does not match certhash in the multiaddr"
                )

            # 7. Build WebRTCConnection and wire callbacks
            conn = WebRTCConnection(
                peer_id=remote_peer_id or ID(b"\x00" * 32),
                bridge=bridge,
                is_initiator=True,
                config=self._config,
                remote_addrs=[maddr],
            )
            await bridge.run_coro(_async_noop(wire_pc_to_connection(pc, conn)))

            # 8. Noise XX handshake over channel 0
            from libp2p.crypto.x25519 import (
                create_new_key_pair as create_x25519_keypair,
            )

            noise_kp = create_x25519_keypair()

            async def _trio_noise_send(data: bytes) -> None:
                await bridge.run_coro(noise_send(data))

            async def _trio_noise_recv() -> bytes:
                return await bridge.run_coro(noise_recv())

            noise_rw = DataChannelReadWriter(
                send_cb=_trio_noise_send,
                recv_cb=_trio_noise_recv,
                is_initiator=True,
            )
            authenticated_peer = await perform_noise_handshake(
                conn=noise_rw,
                local_peer=self._local_peer_id,
                libp2p_privkey=self._private_key,
                noise_static_key=noise_kp.private_key,
                local_fingerprint=self._certificate.fingerprint,
                remote_fingerprint=expected_fp,
                is_initiator=True,
                remote_peer=remote_peer_id,
            )

            # 9. Finalize connection
            conn.peer_id = authenticated_peer
            await conn.start()
            logger.info(
                "WebRTC Direct connection established to %s",
                authenticated_peer,
            )
            return conn

        except WebRTCConnectionError:
            raise
        except Exception as e:
            raise WebRTCConnectionError(f"WebRTC Direct dial failed: {e}") from e

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

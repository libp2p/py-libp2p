"""
WebRTC private-to-private listener.

Registers as a stream handler for ``/webrtc-signaling/0.0.1`` on the
local host.  When a remote peer sends a signaling stream through a relay,
this listener handles the SDP exchange, establishes a direct WebRTC
connection, and calls the handler function.

The listener advertises multiaddrs of the form::

    <relay-multiaddr>/p2p-circuit/webrtc/p2p/<local-peer-id>

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener, INetStream
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from .certificate import WebRTCCertificate
from .config import WebRTCTransportConfig
from .constants import WEBRTC_SIGNALING_PROTOCOL_ID

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebRTCPrivateListener(IListener):
    """
    Listens for incoming WebRTC signaling over Circuit Relay v2.

    Created by :meth:`WebRTCPrivateTransport.create_listener`.
    """

    def __init__(
        self,
        handler_function: THandler,
        private_key: PrivateKey,
        certificate: WebRTCCertificate,
        config: WebRTCTransportConfig,
        bridge_factory: Callable[[], Awaitable[Any]],
        local_peer_id: ID,
        host: object | None = None,
    ) -> None:
        self._handler = handler_function
        self._private_key = private_key
        self._certificate = certificate
        self._config = config
        self._bridge_factory = bridge_factory
        self._local_peer_id = local_peer_id
        self._host = host

        self._listening_addrs: list[Multiaddr] = []
        self._closed = False
        self._nursery: trio.Nursery | None = None

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> None:
        """
        Start listening for WebRTC signaling.

        Registers a stream handler for ``/webrtc-signaling/0.0.1`` on
        the host.  The multiaddr should be a relay address ending with
        ``/webrtc``.

        :param maddr: A ``/p2p-circuit/webrtc`` multiaddr.
        :param nursery: Trio nursery for spawning handler tasks.
        """
        self._nursery = nursery

        # Register the signaling stream handler on the host
        if self._host is not None and hasattr(self._host, "set_stream_handler"):
            self._host.set_stream_handler(  # type: ignore[attr-defined]
                WEBRTC_SIGNALING_PROTOCOL_ID,
                self._handle_signaling_stream,
            )
            logger.info(
                "Registered %s stream handler for WebRTC signaling",
                WEBRTC_SIGNALING_PROTOCOL_ID,
            )

        self._listening_addrs.append(maddr)
        logger.info("WebRTC private listener ready on %s", maddr)

        # NOTE: The full signaling handler sequence (when aiortc is wired up):
        # 1. Receive SDP_OFFER from signaling stream
        # 2. Create RTCPeerConnection
        # 3. Send SDP_ANSWER
        # 4. Exchange ICE candidates with bilateral ICE_DONE
        # 5. Wait for ICE connected
        # 6. Noise XX handshake over data channel 0
        # 7. Create WebRTCConnection, call self._handler(conn)

    async def _handle_signaling_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming signaling stream from a remote peer.

        This is called by the host when a peer opens a stream with
        the ``/webrtc-signaling/0.0.1`` protocol.
        """
        try:
            from .signaling import SignalingSession

            session = SignalingSession(stream)

            # Receive the SDP offer
            offer_bytes = await session.receive_offer()
            logger.debug(
                "Received WebRTC signaling offer (%d bytes) from peer",
                len(offer_bytes),
            )

            # NOTE: When aiortc is wired up:
            # 1. Create RTCPeerConnection from offer SDP
            # 2. Generate answer SDP
            # 3. session.send_answer(answer_sdp)
            # 4. Exchange ICE candidates
            # 5. session.complete()  # bilateral ICE_DONE
            # 6. Noise handshake
            # 7. Create connection, call handler

        except Exception:
            logger.debug("WebRTC signaling handler failed", exc_info=True)
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Return the listening multiaddrs."""
        return tuple(self._listening_addrs)

    async def close(self) -> None:
        """Stop listening and deregister the stream handler."""
        if self._closed:
            return
        self._closed = True

        if self._host is not None and hasattr(self._host, "remove_stream_handler"):
            try:
                self._host.remove_stream_handler(  # type: ignore[attr-defined]
                    WEBRTC_SIGNALING_PROTOCOL_ID
                )
            except Exception:
                pass

        self._listening_addrs.clear()
        logger.debug("WebRTC private listener closed")

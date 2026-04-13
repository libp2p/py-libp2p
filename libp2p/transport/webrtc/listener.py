"""
WebRTC Direct listener.

Binds a UDP socket and accepts incoming WebRTC connections.  The published
multiaddr includes the DTLS certificate hash so remote peers can verify the
server's identity before the Noise handshake.

Published multiaddr format::

    /ip4/<bound-ip>/udp/<bound-port>/webrtc-direct/certhash/<hash>/p2p/<peer-id>

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from .certificate import WebRTCCertificate
from .config import WebRTCTransportConfig
from .multiaddr_utils import (
    build_webrtc_direct_multiaddr,
    parse_webrtc_direct_multiaddr,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WebRTCDirectListener(IListener):
    """
    Listens for incoming WebRTC Direct connections on a UDP socket.

    Created by :meth:`WebRTCDirectTransport.create_listener`.
    """

    def __init__(
        self,
        handler_function: THandler,
        private_key: PrivateKey,
        certificate: WebRTCCertificate,
        config: WebRTCTransportConfig,
        bridge_factory: Callable[[], Awaitable[Any]],
        local_peer_id: ID,
    ) -> None:
        self._handler = handler_function
        self._private_key = private_key
        self._certificate = certificate
        self._config = config
        self._bridge_factory = bridge_factory
        self._local_peer_id = local_peer_id

        self._listening_addrs: list[Multiaddr] = []
        self._closed = False
        self._nursery: trio.Nursery | None = None

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> None:
        """
        Start listening on the given multiaddr.

        :param maddr: A ``/webrtc-direct`` multiaddr (e.g.
            ``/ip4/0.0.0.0/udp/9090/webrtc-direct``).
        :param nursery: Trio nursery for spawning accept tasks.
        :raises WebRTCConnectionError: If binding fails.
        """
        host, port, _certhash, _peer_id = parse_webrtc_direct_multiaddr(maddr)
        self._nursery = nursery

        # Build the advertised multiaddr with our cert hash and peer ID
        certhash_mb = self._certificate.fingerprint_to_multibase()
        advertised = build_webrtc_direct_multiaddr(
            host=host if host != "0.0.0.0" else "127.0.0.1",
            port=port,
            certhash_multibase=certhash_mb,
            peer_id=self._local_peer_id.to_base58(),
        )
        self._listening_addrs.append(advertised)

        logger.info("WebRTC Direct listener bound on %s", advertised)

        # NOTE: The actual UDP socket binding and incoming connection
        # acceptance would be wired up here when aiortc integration is
        # complete.  The accept loop would:
        # 1. Accept DTLS connections on the UDP socket
        # 2. For each: create RTCPeerConnection, Noise handshake
        # 3. Create WebRTCConnection, call self._handler(conn)
        #
        # For Phase 2, the listener advertises the correct multiaddr
        # and the structure is ready for Phase 3 integration.

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Return the listening multiaddrs (includes certhash and peer ID)."""
        return tuple(self._listening_addrs)

    async def close(self) -> None:
        """Stop listening and close all accepted connections."""
        if self._closed:
            return
        self._closed = True
        self._listening_addrs.clear()
        logger.debug("WebRTC Direct listener closed")

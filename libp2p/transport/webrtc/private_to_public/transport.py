import logging

from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import Multiaddr
import trio
from trio_asyncio import aio_as_trio, open_loop

from libp2p.abc import IHost, IListener, IRawConnection, ITransport
from libp2p.custom_types import THandler
from libp2p.peer.id import ID
from libp2p.transport.exceptions import OpenConnectionError

from ..constants import (
    DEFAULT_ICE_SERVERS,
    WebRTCError,
)
from .connect import connect
from .direct_rtc_connection import DirectPeerConnection
from .gen_certificate import (
    WebRTCCertificate,
    parse_webrtc_maddr,
)
from .listener import WebRTCDirectListener
from .util import (
    generate_ufrag,
)

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


class WebRTCDirectTransport(ITransport):
    """
    Provides direct peer-to-peer WebRTC connections without signaling servers.
    """

    def __init__(self) -> None:
        """Initialize WebRTC-Direct transport."""
        self.ice_servers = DEFAULT_ICE_SERVERS
        self.active_connections: dict[str, IRawConnection] = {}
        self.pending_connections: dict[str, RTCPeerConnection] = {}
        self._started = False
        self.host: IHost | None = None
        self.connection_events: dict[str, trio.Event] = {}
        self.cert_mgr: WebRTCCertificate | None = None
        self.supported_protocols: set[str] = {"webrtc-direct", "p2p"}
        logger.info("WebRTC-Direct Transport initialized")

    async def start(self, nursery: trio.Nursery) -> None:
        """Start the WebRTC-Direct transport."""
        if self._started:
            return

        if not self.host:
            raise WebRTCError("Host must be set before starting transport")

        # Generate certificate for this transport
        self.cert_mgr = WebRTCCertificate()

        with trio.CancelScope() as scope:
            self.cert_mgr.cancel_scope = scope
            if self.cert_mgr is not None:
                nursery.start_soon(self.cert_mgr.renewal_loop)

        self._started = True
        logger.info("WebRTC-Direct Transport started")

    async def stop(self) -> None:
        """Stop the WebRTC-Direct transport."""
        if not self._started:
            return

        # Clean up connections
        for conn_id in list(self.active_connections.keys()):
            await self._cleanup_connection(conn_id)

        if self.cert_mgr and self.cert_mgr.cancel_scope:
            self.cert_mgr.cancel_scope.cancel()

        self._started = False
        logger.info("WebRTC-Direct Transport stopped")

    def can_handle(self, maddr: Multiaddr) -> bool:
        """Check if transport can handle the multiaddr."""
        protocols = {p.name for p in maddr.protocols()}
        return bool(protocols.intersection(self.supported_protocols))

    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        Dial a direct WebRTC connection to a peer.
        Uses UDP hole punching and SDP munging for NAT traversal.
        """
        if not self.can_handle(maddr):
            raise OpenConnectionError(f"Cannot handle multiaddr: {maddr}")

        if not self._started:
            raise WebRTCError("Transport not started")

        try:
            ip, peer_id_str, certhash = parse_webrtc_maddr(maddr)
            peer_id = (
                peer_id_str
                if isinstance(peer_id_str, ID)
                else ID.from_base58(str(peer_id_str))
            )

            # Extract port from multiaddr
            port = 9000  # Default port
            try:
                udp_value = maddr.value_for_protocol("udp")
                if udp_value is not None:
                    port = int(udp_value)
            except Exception:
                logger.warning("No UDP port in multiaddr, using default 9000")

            logger.info(f"Dialing WebRTC-Direct to {peer_id} at {ip}:{port}")

            ufrag = generate_ufrag()

            async with open_loop():
                conn_id = str(peer_id)
                rtc_config = RTCConfiguration(iceServers=[])
                direct_peer_connection = (
                    await DirectPeerConnection.create_dialer_rtc_peer_connection(
                        role="client", ufrag=ufrag, rtc_configuration=rtc_config
                    )
                )

                try:
                    connection = await connect(
                        role="client",
                        ufrag=ufrag,
                        peer_connection=direct_peer_connection,
                        remote_addr=maddr,
                    )
                    if connection is None:
                        raise OpenConnectionError("WebRTC-Direct connection failed")
                    self.active_connections[conn_id] = connection
                    self.pending_connections.pop(conn_id, None)
                    self.connection_events.pop(conn_id, None)

                    logger.debug(
                        f"Successfully established WebRTC-direct connection to{peer_id}"
                    )
                    return connection
                except Exception as e:
                    logger.error(f"Failed to connect as client: {e}")
                    await direct_peer_connection.close()
                    raise OpenConnectionError(
                        f"Failed to connect as client: {e}"
                    ) from e

        except Exception as e:
            logger.error(f"Failed to dial WebRTC-Direct connection to {maddr}: {e}")
            raise OpenConnectionError(f"WebRTC-Direct dial failed: {e}") from e

    def create_listener(self, handler_function: THandler) -> IListener:
        """Create a WebRTC-Direct listener for incoming connections."""
        if self.cert_mgr is None:
            raise OpenConnectionError("Cert_mgr not present")
        rtc_config = RTCConfiguration()
        return WebRTCDirectListener(
            transport=self,
            cert=self.cert_mgr,
            rtc_configuration=rtc_config,
        )

    async def _exchange_offer_answer_direct(
        self, peer_id: ID, offer: RTCSessionDescription, certhash: str
    ) -> None:
        """Exchange offer/answer for direct connection via pubsub."""
        # TODO: Implement pubsub-based offer/answer exchange
        # This would use libp2p pubsub to exchange SDP messages
        # WHy??
        logger.debug(f"Exchanging offer/answer with {peer_id} via pubsub")
        pass

    async def _cleanup_connection(self, conn_id: str) -> None:
        """Clean up connection resources."""
        if conn_id in self.pending_connections:
            pc = self.pending_connections.pop(conn_id)
            try:
                async with open_loop():
                    await aio_as_trio(pc.close())
            except Exception as e:
                logger.warning(f"Error closing peer connection {conn_id}: {e}")

        if conn_id in self.active_connections:
            conn = self.active_connections.pop(conn_id)
            try:
                await conn.close()
            except Exception as e:
                logger.warning(f"Error closing raw connection {conn_id}: {e}")

        if conn_id in self.connection_events:
            self.connection_events.pop(conn_id)

    def set_host(self, host: IHost) -> None:
        """Set the libp2p host for this transport."""
        self.host = host

    def get_supported_protocols(self) -> set[str]:
        """Get supported protocols."""
        return self.supported_protocols.copy()

    def get_connection_count(self) -> int:
        """Get number of active connections."""
        return len(self.active_connections)

    def is_started(self) -> bool:
        """Check if transport is started."""
        return self._started

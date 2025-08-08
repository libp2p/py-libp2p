import logging
from typing import Any

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

from ..connection import WebRTCRawConnection
from ..constants import (
    DEFAULT_HANDSHAKE_TIMEOUT,
    DEFAULT_ICE_SERVERS,
    WebRTCError,
)
from ..gen_certificate import (
    WebRTCCertificate,
    create_webrtc_direct_multiaddr,
    parse_webrtc_maddr,
)
from ..udp_hole_punching import UDPHolePuncher
from ..util import (
    SDPMunger,
    WebRTCDirectDiscovery,
)

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


class WebRTCDirectListener(IListener):
    """
    Private-to-public WebRTC-Direct transport implementation.
    Allows direct peer-to-peer WebRTC connections without signaling servers,
    using UDP hole punching and mDNS/libp2p pubsub for peer discovery.
    """

    def __init__(self, transport: Any, handler: THandler) -> None:
        self.transport = transport
        self.handler = handler
        self._is_listening = False
        self.cert_mgr: WebRTCCertificate | None = None
        self.hole_puncher: UDPHolePuncher | None = None
        self.discovery: WebRTCDirectDiscovery | None = None
        self._listen_addrs: list[Multiaddr] = []

    async def listen(self, maddr: Any, nursery: trio.Nursery) -> bool:
        """Start listening for incoming connections."""
        if self._is_listening:
            return True

        try:
            # Generate certificate for this listener
            self.cert_mgr = WebRTCCertificate.generate()

            # Initialize UDP hole puncher
            self.hole_puncher = UDPHolePuncher()

            # Initialize peer discovery
            if self.transport.host:
                self.discovery = WebRTCDirectDiscovery(
                    self.transport.host, self.cert_mgr
                )
                await self.discovery.start_discovery()

            # Create listening multiaddr with certificate hash
            if hasattr(maddr, "value_for_protocol"):
                ip = maddr.value_for_protocol("ip4") or maddr.value_for_protocol("ip6")
                port = maddr.value_for_protocol("udp") or 0
                peer_id = self.transport.host.get_id() if self.transport.host else None

                if ip and peer_id:
                    listen_addr = create_webrtc_direct_multiaddr(ip, port, peer_id)
                    self._listen_addrs.append(listen_addr)

            self._is_listening = True
            logger.info("WebRTC-Direct listener started")
            return True

        except Exception as e:
            logger.error(f"Failed to start WebRTC-Direct listener: {e}")
            return False

    async def close(self) -> None:
        """Close the listener."""
        self._is_listening = False

        if self.discovery:
            # Stop discovery
            pass  # TODO: Implement discovery cleanup

        if self.hole_puncher:
            # Cleanup hole puncher
            pass  # TODO: Implement hole puncher cleanup

        logger.info("WebRTC-Direct listener closed")

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Get listener addresses."""
        return tuple(self._listen_addrs)

    def is_listening(self) -> bool:
        """Check if listener is active."""
        return self._is_listening


class WebRTCDirectTransport(ITransport):
    """
    Provides direct peer-to-peer WebRTC connections without signaling servers.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize WebRTC-Direct transport."""
        self.config = config or {}
        self.ice_servers = self.config.get("ice_servers", DEFAULT_ICE_SERVERS)
        self.active_connections: dict[str, IRawConnection] = {}
        self.pending_connections: dict[str, RTCPeerConnection] = {}
        self.supported_protocols: set[str] = {"webrtc-direct", "p2p"}
        self._started = False
        self.host: IHost | None = None
        self.hole_puncher: UDPHolePuncher | None = None
        self.connection_events: dict[str, trio.Event] = {}
        self.cert_mgr: WebRTCCertificate | None = None

        logger.info("WebRTC-Direct Transport initialized")

    async def start(self) -> None:
        """Start the WebRTC-Direct transport."""
        if self._started:
            return

        if not self.host:
            raise WebRTCError("Host must be set before starting transport")

        # Generate certificate for this transport
        self.cert_mgr = WebRTCCertificate.generate()

        # Initialize UDP hole puncher
        self.hole_puncher = UDPHolePuncher()

        self._started = True
        logger.info("WebRTC-Direct Transport started")

    async def stop(self) -> None:
        """Stop the WebRTC-Direct transport."""
        if not self._started:
            return

        # Clean up connections
        for conn_id in list(self.active_connections.keys()):
            await self._cleanup_connection(conn_id)

        # Clean up hole puncher
        if self.hole_puncher:
            # TODO: Implement proper cleanup
            pass

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
                port = int(maddr.value_for_protocol("udp"))
            except Exception:
                logger.warning("No UDP port in multiaddr, using default 9000")

            logger.info(f"Dialing WebRTC-Direct to {peer_id} at {ip}:{port}")

            # Perform UDP hole punching
            if self.hole_puncher is None:
                raise WebRTCError("hole_puncher is not initialized")

            local_ip, local_port = await self.hole_puncher.punch_hole(ip, port)

            # Create peer connection without STUN/TURN
            config = RTCConfiguration(iceServers=[])

            async with open_loop():
                pc = await aio_as_trio(RTCPeerConnection(config))

                # Store for cleanup
                conn_id = str(peer_id)
                self.pending_connections[conn_id] = pc

                # Create data channel
                channel = await aio_as_trio(
                    pc.createDataChannel("libp2p-webrtc-direct")
                )

                # Setup channel event handlers
                channel_ready = trio.Event()
                self.connection_events[conn_id] = channel_ready

                def on_open() -> None:
                    logger.info(f"WebRTC-Direct channel opened to {peer_id}")
                    channel_ready.set()

                def on_error(error: Any) -> None:
                    logger.error(f"WebRTC-Direct channel error: {error}")

                def on_ice_candidate(candidate: Any) -> None:
                    if candidate:
                        ice_candidates.append(candidate)
                        logger.debug(f"ICE candidate generated: {candidate.type}")

                # Setup channel event handlers
                channel.on("open", on_open)
                channel.on("error", on_error)

                # Setup ICE candidate handling
                ice_candidates: list[Any] = []
                pc.on("icecandidate", on_ice_candidate)

                # Create offer
                offer = await aio_as_trio(pc.createOffer())

                # Munge SDP for direct connection
                munged_sdp = SDPMunger.munge_offer(offer.sdp, local_ip, local_port)
                offer = RTCSessionDescription(sdp=munged_sdp, type=offer.type)

                # Set local description
                await aio_as_trio(pc.setLocalDescription(offer))

                # Exchange offer/answer via pubsub (for direct connections)
                await self._exchange_offer_answer_direct(peer_id, offer, certhash)

                with trio.move_on_after(DEFAULT_HANDSHAKE_TIMEOUT) as cancel_scope:
                    await channel_ready.wait()

                if cancel_scope.cancelled_caught:
                    raise WebRTCError("WebRTC-Direct connection timeout")

                # Create connection object
                connection = WebRTCRawConnection(
                    peer_id, pc, channel, is_initiator=True
                )

                # Track connection
                self.active_connections[conn_id] = connection
                self.pending_connections.pop(conn_id, None)
                self.connection_events.pop(conn_id, None)

                logger.info(
                    f"Successfully established WebRTC-Direct connection to {peer_id}"
                )
                return connection

        except Exception as e:
            logger.error(f"Failed to dial WebRTC-Direct connection to {maddr}: {e}")
            raise OpenConnectionError(f"WebRTC-Direct dial failed: {e}") from e

    def create_listener(self, handler_function: THandler) -> IListener:
        """Create a WebRTC-Direct listener for incoming connections."""
        return WebRTCDirectListener(transport=self, handler=handler_function)

    async def _exchange_offer_answer_direct(
        self, peer_id: ID, offer: RTCSessionDescription, certhash: str
    ) -> None:
        """Exchange offer/answer for direct connection via pubsub."""
        # TODO: Implement pubsub-based offer/answer exchange
        # This would use libp2p pubsub to exchange SDP messages
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

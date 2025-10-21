import asyncio
from asyncio import AbstractEventLoop
import logging
from typing import Any

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection
from multiaddr import Multiaddr
from trio_asyncio import aio_as_trio, open_loop

from libp2p.abc import (
    IListener,
    INetworkService,
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import THandler, TProtocol
from libp2p.host.basic_host import IHost
from libp2p.transport.exceptions import OpenConnectionError

from ..constants import (
    DEFAULT_DIAL_TIMEOUT,
    DEFAULT_ICE_SERVERS,
    SIGNALING_PROTOCOL,
    WebRTCError,
)
from ..private_to_public.util import (
    pick_random_ice_servers,
)
from .initiate_connection import initiate_connection
from .listener import WebRTCPeerListener
from .signaling_stream_handler import handle_incoming_stream

logger = logging.getLogger("libp2p.transport.webrtc.private_to_private")


class WebRTCTransport(ITransport):
    """
    Private-to-private WebRTC transport implementation.
    Uses circuit relays for signaling and STUN/TURN servers for NAT traversal.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize WebRTC transport."""
        self.config = config or {}

        # ICE servers configuration
        self.ice_servers = self.config.get("ice_servers", DEFAULT_ICE_SERVERS)

        # Connection tracking
        self.active_connections: dict[str, IRawConnection] = {}
        self.pending_connections: dict[str, RTCPeerConnection] = {}

        # Protocol support
        self.supported_protocols: set[str] = {"webrtc", "p2p-circuit", "p2p"}

        # Transport state
        self._started = False
        self.host: IHost | None = None
        self._network: INetworkService | None = None

        # Trio-asyncio integration
        self._asyncio_loop: AbstractEventLoop | None = None
        self._loop_future = None

        # Metrics and monitoring
        self.metrics = None

        logger.info("WebRTC Transport initialized")

    async def start(self) -> None:
        """Start the WebRTC transport with proper asyncio event loop setup."""
        if self._started:
            return

        if not self.host:
            raise WebRTCError("Host must be set before starting transport")

        try:
            # Ensure we have an asyncio event loop for aiortc
            try:
                self._asyncio_loop = asyncio.get_running_loop()
                logger.debug("Using existing asyncio event loop")
            except RuntimeError:
                # open_loop() returns an AsyncContextManager, not an
                #  AbstractEventLoop, hence
                # use it in context managers when needed
                logger.debug(
                    "No asyncio event loop"
                    "-using trio_asyncio context managers for aiortc operations"
                )

            # Register signaling protocol handler with the host
            # This follows the pattern used by other protocols like DHT and pubsub
            self.host.set_stream_handler(
                TProtocol(SIGNALING_PROTOCOL), self._handle_signaling_stream
            )
            logger.info(f"Registered signaling protocol handler: {SIGNALING_PROTOCOL}")

            self._started = True
            logger.info("WebRTC Transport started successfully")

        except Exception as e:
            logger.error(f"Failed to start WebRTC transport: {e}")
            raise WebRTCError(f"Transport start failed: {e}") from e

    async def stop(self) -> None:
        """Stop the WebRTC transport and clean up resources."""
        if not self._started:
            return

        try:
            connection_ids = list(self.active_connections.keys())
            for conn_id in connection_ids:
                await self._cleanup_connection(conn_id)

            # Close all pending connections
            pending_ids = list(self.pending_connections.keys())
            for conn_id in pending_ids:
                await self._cleanup_connection(conn_id)

            self._started = False
            logger.info("WebRTC Transport stopped successfully")

        except Exception as e:
            logger.error(f"Error stopping WebRTC transport: {e}")
            raise

    def can_handle(self, maddr: Multiaddr) -> bool:
        """
        Check if transport can handle the multiaddr.

        WebRTC transport can handle multiaddrs that contain:
        - webrtc protocol
        - p2p-circuit protocol (for relay-based connections)
        - p2p protocol (for peer addressing)
        """
        try:
            protocols = {p.name for p in maddr.protocols()}

            # Must contain webrtc or p2p-circuit for WebRTC signaling
            has_webrtc = "webrtc" in protocols
            has_circuit = "p2p-circuit" in protocols
            has_p2p = "p2p" in protocols

            # For WebRTC transport, we need either:
            # 1. Direct webrtc protocol, OR
            # 2. p2p-circuit for relay-based signaling
            return has_webrtc or (has_circuit and has_p2p)

        except Exception as e:
            logger.warning(f"Error checking multiaddr compatibility: {e}")
            return False

    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        Dial a WebRTC peer using circuit relay for signaling.

        Args:
            maddr: Multiaddr containing circuit relay path and target peer

        Returns:
            IRawConnection: Established WebRTC connection

        """
        if not self.can_handle(maddr):
            raise OpenConnectionError(f"Cannot handle multiaddr: {maddr}")

        if not self._started:
            raise WebRTCError("Transport not started")

        if self.host is None:
            raise WebRTCError("Host must be set before dialing connections")

        logger.info(f"Dialing WebRTC connection to {maddr}")

        try:
            # Configure peer connection with ICE servers
            ice_servers = pick_random_ice_servers(self.ice_servers)
            rtc_ice_servers = [
                RTCIceServer(**s) if not isinstance(s, RTCIceServer) else s
                for s in ice_servers
            ]
            rtc_config = RTCConfiguration(iceServers=rtc_ice_servers)

            # Initiate connection through circuit relay with proper async context
            async with open_loop():
                connection = await initiate_connection(
                    maddr=maddr,
                    rtc_config=rtc_config,
                    host=self.host,
                    timeout=DEFAULT_DIAL_TIMEOUT,
                )

            # Track connection
            remote_peer_id = getattr(connection, "remote_peer_id", None)
            conn_id = (
                str(remote_peer_id)
                if remote_peer_id is not None
                else str(id(connection))
            )
            self.active_connections[conn_id] = connection
            logger.info(
                f"Successfully established WebRTC connection to {remote_peer_id}"
            )
            return connection

        except Exception as e:
            logger.error(f"Failed to dial WebRTC connection to {maddr}: {e}")
            raise OpenConnectionError(f"WebRTC dial failed: {e}") from e

    def create_listener(self, handler_function: THandler) -> IListener:
        """Create a WebRTC listener for incoming connections."""
        if self.host is None:
            raise WebRTCError("Host must be set before creating listener")

        return WebRTCPeerListener(
            transport=self, handler=handler_function, host=self.host
        )

    async def _handle_signaling_stream(self, stream: Any) -> None:
        """
        Handle incoming signaling stream from circuit relay with proper async context.

        This follows the py-libp2p stream handler pattern where the handler
        receives only the stream object.
        """
        if self.host is None:
            logger.error("Cannot handle signaling stream: Host not set")
            return

        connection_info = None

        try:
            # Extract connection info from stream
            if hasattr(stream, "muxed_conn") and hasattr(stream.muxed_conn, "peer_id"):
                connection_info = {
                    "peer_id": stream.muxed_conn.peer_id,
                    "remote_addr": getattr(stream.muxed_conn, "remote_addr", None),
                }

            logger.debug(f"Handling incoming signaling stream from {connection_info}")

            # Configure peer connection
            ice_servers = pick_random_ice_servers(self.ice_servers)
            rtc_ice_servers = [
                RTCIceServer(**s) if not isinstance(s, RTCIceServer) else s
                for s in ice_servers
            ]
            rtc_config = RTCConfiguration(iceServers=rtc_ice_servers)

            # Handle the signaling stream with proper async context
            async with open_loop():
                result = await handle_incoming_stream(
                    stream=stream,
                    rtc_config=rtc_config,
                    connection_info=connection_info,
                    host=self.host,
                )

            # Track connection if successful
            if result:
                remote_peer_id = getattr(result, "remote_peer_id", None)
                conn_id = (
                    str(remote_peer_id)
                    if remote_peer_id is not None
                    else str(id(result))
                )
                self.active_connections[conn_id] = result
                logger.info(f"Successfully handled connection from {remote_peer_id}")

                # TODO: Notify the application layer about the new connection
                # This would typically go through the host's connection manager

            else:
                logger.warning("Signaling stream handling returned no connection")

        except Exception as e:
            logger.error(f"Error handling signaling stream: {e}")
            # Ensure stream is closed on error
            try:
                if hasattr(stream, "close"):
                    await stream.close()
            except Exception as close_error:
                logger.warning(f"Error closing signaling stream: {close_error}")

    async def _cleanup_connection(self, conn_id: str) -> None:
        """Clean up connection resources with proper async handling."""
        try:
            # Clean up pending peer connection
            if conn_id in self.pending_connections:
                pc = self.pending_connections.pop(conn_id)
                try:
                    async with open_loop():
                        await aio_as_trio(pc.close())
                    logger.debug(f"Closed pending peer connection {conn_id}")
                except Exception as e:
                    logger.warning(f"Error closing peer connection {conn_id}: {e}")

            # Clean up active raw connection
            if conn_id in self.active_connections:
                conn = self.active_connections.pop(conn_id)
                try:
                    await conn.close()
                    logger.debug(f"Closed active connection {conn_id}")
                except Exception as e:
                    logger.warning(f"Error closing raw connection {conn_id}: {e}")

        except Exception as e:
            logger.error(f"Error in connection cleanup for {conn_id}: {e}")

    async def _on_protocol(self, stream: Any) -> None:
        """
        Handle incoming signaling stream (following JS pattern).
        
        Reference: _onProtocol method in transport.ts
        """
        if not self.host:
            logger.error("Cannot handle signaling stream: Host not set")
            return

        logger.debug("Handling incoming signaling protocol stream")
        
        try:
            ice_servers = pick_random_ice_servers(self.ice_servers)
            rtc_ice_servers = [
                RTCIceServer(**s) if not isinstance(s, RTCIceServer) else s
                for s in ice_servers
            ]
            rtc_config = RTCConfiguration(iceServers=rtc_ice_servers)
            
            async with open_loop():
                peer_connection = RTCPeerConnection(rtc_config)
                
                result = await handle_incoming_stream(
                    stream=stream,
                    rtc_config=rtc_config,
                    connection_info=None,
                    host=self.host,
                    timeout=DEFAULT_DIAL_TIMEOUT,
                )
                
                if result:
                    remote_peer_id = getattr(result, "remote_peer_id", None)
                    conn_id = str(remote_peer_id) if remote_peer_id else str(id(result))
                    self.active_connections[conn_id] = result
                    
                    logger.info(f"Successfully handled WebRTC connection from {remote_peer_id}")
                else:
                    logger.warning("Signaling stream handling failed")
                    
        except Exception as e:
            logger.error(f"Error in _on_protocol: {e}")
            try:
                if hasattr(stream, 'close'):
                    await stream.close()
            except Exception:
                pass

    def set_host(self, host: IHost) -> None:
        """Set the libp2p host for this transport."""
        self.host = host

        # Store reference to network for potential future use
        if hasattr(host, "get_network"):
            self._network = host.get_network()
            logger.debug("Stored network reference from host")

    def get_supported_protocols(self) -> set[str]:
        """Get supported protocols."""
        return self.supported_protocols.copy()

    def get_connection_count(self) -> int:
        """Get number of active connections."""
        return len(self.active_connections)

    def is_started(self) -> bool:
        """Check if transport is started."""
        return self._started

    def get_addrs(self) -> list[Multiaddr]:
        """
        Get the multiaddresses this transport is listening on.

        For WebRTC transport, we don't listen on specific addresses like TCP.
        Instead, we listen for signaling via the circuit relay protocol.
        """
        if not self._started or not self.host:
            return []

        # TODO: Return circuit relay addresses that can be used for WebRTC signaling
        return []
    
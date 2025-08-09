import logging
from typing import Any

from aiortc import RTCConfiguration, RTCIceServer
from multiaddr import Multiaddr
import trio

from libp2p.abc import IHost, IListener, INetStream
from libp2p.custom_types import THandler, TProtocol
from libp2p.relay.circuit_v2 import (
    CircuitV2Protocol,
    RelayDiscovery,
    RelayLimits,
)
from libp2p.relay.circuit_v2.config import RelayConfig

from ..constants import (
    DEFAULT_DIAL_TIMEOUT,
    DEFAULT_ICE_SERVERS,
    SIGNALING_PROTOCOL,
)
from ..private_to_private.signaling_stream_handler import handle_incoming_stream
from ..signal_service import SignalService

logger = logging.getLogger("private_to_private.listener")


class WebRTCPeerListener(IListener):
    """
    WebRTC peer listener for private-to-private connections.
    Listens for incoming WebRTC connections through circuit relay signaling.
    """

    def __init__(self, transport: object, handler: THandler, host: IHost) -> None:
        """Initialize WebRTC peer listener."""
        self.transport = transport
        self.handler = handler
        self.host = host
        self._is_listening = False

        # Circuit relay components
        self.relay_config: RelayConfig | None = None
        self.relay_protocol: CircuitV2Protocol | None = None
        self.relay_discovery: RelayDiscovery | None = None

        # WebRTC signaling components
        self.signal_service: SignalService | None = None
        self.signaling_protocol = TProtocol(SIGNALING_PROTOCOL)
        self.rtc_config: RTCConfiguration | None = None  # Declare rtc_config attribute

        # Active connections and streams
        self.active_signaling_streams: dict[str, INetStream] = {}
        self.pending_connections: dict[str, Any] = {}

        # Nursery for managing tasks
        self._nursery: trio.Nursery | None = None

        logger.info("WebRTC peer listener initialized")

    async def listen(self, maddr: object, nursery: trio.Nursery) -> bool:
        """Start listening for incoming connections."""
        if self._is_listening:
            return True

        logger.info("Starting WebRTC peer listener with circuit relay support")
        self._nursery = nursery

        try:
            # Step 1: Initialize circuit relay configuration
            await self._setup_circuit_relay()

            # Step 2: Start relay discovery and reservation
            await self._initialize_relay_discovery()

            # Step 3: Register signaling stream handler
            await self._setup_signaling_handler()

            # Step 4: Start listening for WebRTC connections
            await self._start_webrtc_listening()

            self._is_listening = True
            logger.info("WebRTC peer listener started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to start WebRTC peer listener: {e}")
            return False

    async def _setup_circuit_relay(self) -> None:
        """Configure circuit relay for WebRTC signaling."""
        logger.debug("Setting up circuit relay configuration")

        # Configure relay for client mode (using relays for signaling)
        self.relay_config = RelayConfig(
            enable_hop=False,  # Don't act as relay
            enable_stop=True,  # Accept relayed connections
            enable_client=True,  # Use relays for outgoing connections
            min_relays=2,
            max_relays=5,
            discovery_interval=120,  # Check for relays every 2 minutes
            limits=RelayLimits(
                duration=3600,  # 1 hour connections
                data=100 * 1024 * 1024,  # 100MB per connection
                max_circuit_conns=10,
                max_reservations=5,
            ),
        )

        # Initialize circuit relay protocol
        if self.relay_config is None:
            raise RuntimeError("relay_config is None after initialization")

        self.relay_protocol = CircuitV2Protocol(
            host=self.host,
            limits=self.relay_config.limits,
            allow_hop=self.relay_config.enable_hop,
        )

        logger.debug("Circuit relay configuration completed")

    async def _initialize_relay_discovery(self) -> None:
        """Initialize relay discovery and make reservations."""
        logger.debug("Initializing relay discovery")

        if self.relay_config is None:
            logger.error("Cannot initialize relay discovery: relay_config is None")
            return

        # Start relay discovery
        self.relay_discovery = RelayDiscovery(
            host=self.host,
            auto_reserve=self.relay_config.enable_client,
            discovery_interval=self.relay_config.discovery_interval,
            max_relays=self.relay_config.max_relays,
        )

        # Start discovery in background
        if self._nursery:
            self._nursery.start_soon(self._run_relay_discovery)

        # Wait a bit for initial discovery
        await trio.sleep(1.0)

        # Try to make initial reservations with discovered relays
        await self._make_initial_reservations()

        logger.debug("Relay discovery initialized")

    async def _run_relay_discovery(self) -> None:
        """Run relay discovery continuously."""
        try:
            if self.relay_discovery is None:
                logger.error("Cannot start relay discovery: relay_discovery is None")
                return
            await self.relay_discovery.run()
            logger.debug("Relay discovery service started")
        except Exception as e:
            logger.error(f"Relay discovery error: {e}")

    async def _make_initial_reservations(self) -> None:
        """Make initial reservations with discovered relays."""
        try:
            if self.relay_discovery is None:
                logger.error("Cannot make reservations: relay_discovery is None")
                return

            relays = self.relay_discovery.get_relays()
            reservation_count = 0

            for relay_id in relays[:3]:  # Try first 3 relays
                try:
                    if self.relay_discovery is not None:
                        success = await self.relay_discovery.make_reservation(relay_id)
                        if success:
                            reservation_count += 1
                            logger.debug(f"Made reservation with relay {relay_id}")
                except Exception as e:
                    logger.warning(f"Failed to make reservation with {relay_id}: {e}")

            if reservation_count > 0:
                logger.info(f"Made {reservation_count} relay reservations")
            else:
                logger.warning(
                    "No relay reservations made - WebRTC signaling may be limited"
                )

        except Exception as e:
            logger.error(f"Error making initial reservations: {e}")

    async def _setup_signaling_handler(self) -> None:
        """Set up WebRTC signaling stream handler."""
        logger.debug("Setting up WebRTC signaling handler")

        # Initialize signal service for WebRTC signaling
        self.signal_service = SignalService(self.host)

        # Register stream handler for incoming signaling streams
        self.host.set_stream_handler(
            self.signaling_protocol, self._handle_incoming_signaling_stream
        )

        logger.debug("WebRTC signaling handler registered")

    async def _start_webrtc_listening(self) -> None:
        """Start listening for WebRTC connections."""
        logger.debug("Starting WebRTC connection listening")

        # Set up WebRTC configuration
        ice_servers = [RTCIceServer(**server) for server in DEFAULT_ICE_SERVERS]
        self.rtc_config = RTCConfiguration(iceServers=ice_servers)

        logger.debug("WebRTC listening configuration ready")

    async def _handle_incoming_signaling_stream(self, stream: INetStream) -> None:
        """
        Handle incoming WebRTC signaling stream through circuit relay.

        This is called when a remote peer opens a signaling stream to us
        for WebRTC connection establishment.
        """
        peer_id = stream.muxed_conn.peer_id
        peer_id_str = str(peer_id)

        logger.info(f"Received incoming signaling stream from {peer_id}")

        try:
            # Track the signaling stream
            self.active_signaling_streams[peer_id_str] = stream

            # Extract connection info
            connection_info = {
                "peer_id": peer_id,
                "remote_addr": getattr(stream.muxed_conn, "remote_addr", None),
                "stream_id": id(stream),
            }

            # Handle the WebRTC signaling handshake
            if self.rtc_config is None:
                logger.error("RTCconfig is None, cannot handle signaling stream")
                return

            connection = await handle_incoming_stream(
                stream=stream,
                rtc_config=self.rtc_config,
                connection_info=connection_info,
                host=self.host,
                timeout=DEFAULT_DIAL_TIMEOUT,
            )

            if connection:
                # Store pending connection
                self.pending_connections[peer_id_str] = connection

                # Call the handler with the established connection
                if self.handler is not None:
                    await self.handler(connection)

                logger.info(
                    f"Successfully established WebRTC connection with {peer_id}"
                )
            else:
                logger.warning(f"Failed to establish WebRTC connection with {peer_id}")

        except Exception as e:
            logger.error(f"Error handling signaling stream from {peer_id}: {e}")
        finally:
            if peer_id_str in self.active_signaling_streams:
                del self.active_signaling_streams[peer_id_str]

            try:
                await stream.close()
            except Exception as e:
                logger.debug(f"Error closing signaling stream: {e}")

    async def close(self) -> None:
        """Stop listening and close the listener."""
        if not self._is_listening:
            return

        logger.info("Closing WebRTC peer listener")

        try:
            await self._unregister_handlers()
            await self._close_signaling_streams()
            await self._close_pending_connections()

            self._is_listening = False
            logger.info("WebRTC peer listener closed successfully")

        except Exception as e:
            logger.error(f"Error during listener cleanup: {e}")

    async def _unregister_handlers(self) -> None:
        """Unregister stream handlers."""
        try:
            # Remove signaling protocol handler
            # using the multiselect interface
            if hasattr(self.host, "get_mux"):
                mux = self.host.get_mux()
                if hasattr(mux, "handlers") and isinstance(mux.handlers, dict):
                    # Remove the handler by setting it to None
                    mux.handlers[self.signaling_protocol] = None
                    logger.debug("Unregistered WebRTC signaling handler")
        except Exception as e:
            logger.warning(f"Error unregistering stream handlers: {e}")

    async def _close_signaling_streams(self) -> None:
        """Close all active signaling streams."""
        if not self.active_signaling_streams:
            return

        logger.debug(f"Closing {len(self.active_signaling_streams)} signaling streams")

        for peer_id_str, stream in list(self.active_signaling_streams.items()):
            try:
                await stream.close()
                logger.debug(f"Closed signaling stream for {peer_id_str}")
            except Exception as e:
                logger.warning(f"Error closing signaling stream for {peer_id_str}: {e}")

        self.active_signaling_streams.clear()

    async def _close_pending_connections(self) -> None:
        """Close all pending WebRTC connections."""
        if not self.pending_connections:
            return

        logger.debug(f"Closing {len(self.pending_connections)} pending connections")

        for peer_id_str, connection in list(self.pending_connections.items()):
            try:
                if hasattr(connection, "close"):
                    await connection.close()
                    logger.debug(f"Closed connection for {peer_id_str}")
            except Exception as e:
                logger.warning(f"Error closing connection for {peer_id_str}: {e}")

        self.pending_connections.clear()

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Get listener addresses as WebRTC multiaddrs."""
        if not self._is_listening:
            return tuple()

        try:
            # Get the peer ID
            peer_id = self.host.get_id() if self.host else None
            if not peer_id:
                return tuple()

            # Get available relays for circuit addresses
            addrs = []

            if self.relay_discovery is not None:
                relays = self.relay_discovery.get_relays()

                # Create circuit relay multiaddrs through each relay
                for relay_id in relays:
                    try:
                        # Get relay addresses from peerstore
                        relay_addrs = (
                            self.host.get_peerstore().peer_info(relay_id).addrs
                        )

                        for relay_addr in relay_addrs:
                            circuit_addr = relay_addr.encapsulate(
                                Multiaddr(
                                    f"/p2p/{relay_id}/p2p-circuit/webrtc/p2p/{peer_id}"
                                )
                            )
                            addrs.append(circuit_addr)

                    except Exception as e:
                        logger.debug(
                            f"Error creating multiaddr for relay {relay_id}: {e}"
                        )

            # If no relays available, create a generic WebRTC multiaddr
            if not addrs and peer_id:
                generic_addr = Multiaddr(f"/webrtc/p2p/{peer_id}")
                addrs.append(generic_addr)

            logger.debug(f"Generated {len(addrs)} WebRTC listener addresses")
            return tuple(addrs)

        except Exception as e:
            logger.error(f"Error generating listener addresses: {e}")
            return tuple()

    def is_listening(self) -> bool:
        """Check if listener is active."""
        return self._is_listening

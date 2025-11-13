import asyncio
from asyncio import AbstractEventLoop
import logging
from typing import TYPE_CHECKING, Any, cast

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection
from multiaddr import Multiaddr
import trio
from trio_asyncio import aio_as_trio, open_loop

from libp2p.abc import (
    IListener,
    INetStream,
    INetworkService,
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import THandler, TProtocol
from libp2p.host.basic_host import IHost
from libp2p.network.transport_manager import TransportManager
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2.config import RelayConfig, RelayLimits, RelayRole
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.stream_muxer.yamux.yamux import YamuxStream
from libp2p.tools.async_service.abc import ManagerAPI
from libp2p.tools.async_service.trio_service import TrioManager
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
from .util import extract_relay_base_addr, get_relay_peer, split_addr

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

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

        # Circuit relay discovery integration
        self._relay_discovery: RelayDiscovery | None = None
        self._relay_protocol: CircuitV2Protocol | None = None
        self._relay_protocol_manager: TrioManager | None = None
        self._relay_discovery_manager: ManagerAPI | None = None
        self._relay_transport: CircuitV2Transport | None = None
        self._relay_limits: RelayLimits | None = None
        self._relay_config: RelayConfig | None = None

        # Transport manager integration
        self._transport_manager: TransportManager | None = None
        self._signaling_ready: set[ID] = set()
        self._advertised_addrs: list[Multiaddr] = []

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

            await self._setup_circuit_relay_support()

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

            if self._relay_discovery_manager is not None:
                await self._relay_discovery_manager.stop()
                self._relay_discovery_manager = None

            if self._relay_protocol_manager is not None:
                await self._relay_protocol_manager.stop()
                self._relay_protocol_manager = None

            self._relay_transport = None
            self._relay_discovery = None
            self._signaling_ready.clear()
            self._advertised_addrs = []

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
            await self.ensure_signaling_connection(maddr)

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

        listener = WebRTCPeerListener(
            transport=self, handler=handler_function, host=self.host
        )
        if self._transport_manager is not None:
            self._transport_manager.register_listener(listener)
        return listener

    async def _handle_signaling_stream(self, stream: INetStream) -> None:
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
            stream_for_info = cast(YamuxStream, stream)
            if hasattr(stream_for_info, "muxed_conn") and hasattr(
                stream_for_info.muxed_conn, "peer_id"
            ):
                connection_info = {
                    "peer_id": stream_for_info.muxed_conn.peer_id,
                    "remote_addr": getattr(
                        stream_for_info.muxed_conn, "remote_addr", None
                    ),
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
                await self.register_incoming_connection(result)
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

    async def _setup_circuit_relay_support(self) -> None:
        if not self.host:
            raise WebRTCError("Host must be set before starting transport")

        self._transport_manager = getattr(
            self.host.get_network(), "transport_manager", None
        )

        if (
            self._transport_manager is not None
            and self._transport_manager.get_transport("webrtc") is None
        ):
            self._transport_manager.register_transport("webrtc", self)

        if self._relay_transport:
            return

        # Prepare relay configuration (client role with auto reservation)
        self._relay_limits = RelayLimits(
            duration=60 * 60,
            data=1024 * 1024 * 10,
            max_circuit_conns=8,
            max_reservations=4,
        )
        self._relay_config = RelayConfig(roles=RelayRole.CLIENT)

        self._relay_protocol = CircuitV2Protocol(
            self.host,
            self._relay_limits,
            allow_hop=False,
        )
        self._relay_protocol_manager = TrioManager(self._relay_protocol)
        trio.lowlevel.spawn_system_task(
            self._relay_protocol_manager.run, name="webrtc-relay-protocol"
        )
        await self._relay_protocol_manager.wait_started()

        self._relay_transport = CircuitV2Transport(
            self.host,
            self._relay_protocol,
            self._relay_config,
        )

        self._relay_discovery = self._relay_transport.discovery
        if self._relay_discovery:
            self._relay_discovery_manager = (
                self._relay_protocol_manager.run_child_service(
                    self._relay_discovery, daemon=True, name="webrtc-relay-discovery"
                )
            )
            await self._relay_discovery_manager.wait_started()

        if (
            self._transport_manager is not None
            and self._transport_manager.get_transport("circuit-relay") is None
        ):
            self._transport_manager.register_transport(
                "circuit-relay", self._relay_transport
            )

    async def ensure_signaling_connection(self, maddr: Multiaddr) -> None:
        if self.host is None:
            raise WebRTCError("Transport host not configured")

        await self._setup_circuit_relay_support()

        circuit_addr, target_peer_id = split_addr(maddr)
        peerstore = self.host.get_peerstore()

        target_component = Multiaddr(f"/p2p/{target_peer_id.to_base58()}")
        try:
            relay_circuit_base = circuit_addr.decapsulate(target_component)
        except ValueError:
            relay_circuit_base = circuit_addr

        try:
            peerstore.add_addr(target_peer_id, relay_circuit_base, 3600)
        except Exception:
            logger.debug(
                "Failed to cache relay base address for %s", target_peer_id.to_base58()
            )

        network_service = self.host.get_network()
        swarm = cast("Swarm", network_service)
        existing = swarm.get_connections(target_peer_id)
        if existing:
            self._signaling_ready.add(target_peer_id)
            return

        if self._relay_transport is None:
            raise WebRTCError("Circuit relay transport not initialized")

        relay_peer = get_relay_peer(circuit_addr)
        base_addr = extract_relay_base_addr(circuit_addr)
        if base_addr is not None:
            peerstore.add_addr(relay_peer, base_addr, 3600)

        try:
            await swarm.dial_peer(relay_peer)
        except Exception as exc:
            raise WebRTCError(f"Failed to dial relay {relay_peer}: {exc}") from exc

        if self._relay_discovery:
            try:
                await self._relay_discovery.make_reservation(relay_peer)
            except Exception:
                pass

        try:
            peer_info = PeerInfo(target_peer_id, [circuit_addr])
            raw_conn = await self._relay_transport.dial_peer_info(peer_info)
        except Exception as exc:
            raise WebRTCError(f"Failed to dial target via relay: {exc}") from exc

        try:
            secured_conn = await swarm.upgrader.upgrade_security(
                raw_conn, True, target_peer_id
            )
            muxed_conn = await swarm.upgrader.upgrade_connection(
                secured_conn, target_peer_id
            )
            await swarm.add_conn(muxed_conn)
            self._signaling_ready.add(target_peer_id)
        except Exception as exc:
            await raw_conn.close()
            raise WebRTCError(
                f"Failed to upgrade relay connection for {target_peer_id}: {exc}"
            ) from exc

    def get_listener_addresses(self) -> list[Multiaddr]:
        if not self.host or self._relay_transport is None:
            return []

        if not self._advertised_addrs:
            self._refresh_listener_addresses()

        return list(self._advertised_addrs)

    async def ensure_listener_ready(self) -> None:
        if not self.host:
            raise WebRTCError("Transport host not configured")

        await self._setup_circuit_relay_support()

        if self._relay_discovery is None:
            raise WebRTCError("Relay discovery not available")

        relays = self._relay_discovery.get_relays()
        relay_list = [str(r) for r in relays]
        logger.info("Relay discovery initial relays: %s", relay_list)
        print("relay discovery initial relays:", relay_list)
        if not relays:
            await self._relay_discovery.discover_relays()
            relays = self._relay_discovery.get_relays()
            relay_list = [str(r) for r in relays]
            logger.info("Relay discovery after manual discover: %s", relay_list)
            print("relay discovery after manual discover:", relay_list)

        reservation_failed = False
        for relay_id in relays:
            try:
                if self._relay_discovery.auto_reserve:
                    await self._relay_discovery.make_reservation(relay_id)
            except Exception:
                reservation_failed = True
                continue

        relay_list = [str(r) for r in relays]
        logger.info(
            "Ensure listener ready using relays: %s (reservation_failed=%s)",
            relay_list,
            reservation_failed,
        )
        print(
            "ensure_listener_ready relays:",
            relay_list,
            "reservation_failed=",
            reservation_failed,
        )
        if reservation_failed:
            logger.debug("Relay reservation failed for at least one relay")

        self._refresh_listener_addresses()
        advertised_list = [str(addr) for addr in self._advertised_addrs]
        logger.info("Advertised listener addrs: %s", advertised_list)
        print("advertised listener addrs:", advertised_list)

    def _refresh_listener_addresses(self) -> None:
        if not self.host:
            return

        peerstore = self.host.get_peerstore()
        local_peer = self.host.get_id()

        advertised: list[Multiaddr] = []
        seen: set[str] = set()

        relay_ids: list[ID]
        if self._relay_discovery:
            relay_ids = self._relay_discovery.get_relays()
        else:
            relay_ids = []

        if not relay_ids:
            try:
                peer_ids: list[ID] = list(getattr(peerstore, "peer_ids", lambda: [])())
            except Exception:
                peer_ids = []
            relay_ids = [pid for pid in peer_ids if pid != local_peer]

        for relay_id in relay_ids:
            relay_addrs = peerstore.addrs(relay_id)
            if not relay_addrs:
                continue

            for relay_addr in relay_addrs:
                base_addr = self._build_relay_base_addr(relay_addr, relay_id)
                if base_addr is None:
                    continue

                try:
                    webrtc_addr = base_addr.encapsulate(
                        Multiaddr(f"/webrtc/p2p/{local_peer.to_base58()}")
                    )
                except Exception as exc:
                    logger.debug("Failed to compose WebRTC listen addr: %s", exc)
                    continue

                addr_str = str(webrtc_addr)
                if addr_str in seen:
                    continue
                seen.add(addr_str)
                advertised.append(webrtc_addr)

                try:
                    peerstore.add_addr(local_peer, base_addr, 3600)
                except Exception:
                    pass

        self._advertised_addrs = advertised

    @staticmethod
    def _build_relay_base_addr(relay_addr: Multiaddr, relay_id: ID) -> Multiaddr | None:
        """
        Normalise relay address to include /p2p/<relay>/p2p-circuit.
        """
        try:
            addr = relay_addr
            relay_component = f"/p2p/{relay_id.to_base58()}"
            addr_str = str(addr)

            if relay_component not in addr_str:
                addr = addr.encapsulate(Multiaddr(relay_component))
                addr_str = str(addr)

            if "/p2p-circuit" not in addr_str:
                addr = addr.encapsulate(Multiaddr("/p2p-circuit"))

            return addr
        except Exception as exc:
            logger.debug("Failed to normalise relay base addr: %s", exc)
            return None

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

    async def _on_protocol(self, stream: INetStream) -> None:
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
                result = await handle_incoming_stream(
                    stream=stream,
                    rtc_config=rtc_config,
                    connection_info=None,
                    host=self.host,
                    timeout=DEFAULT_DIAL_TIMEOUT,
                )

                if result:
                    await self.register_incoming_connection(result)
                else:
                    logger.warning("Signaling stream handling failed")

        except Exception as e:
            logger.error(f"Error in _on_protocol: {e}")
            try:
                if hasattr(stream, "close"):
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

    async def register_incoming_connection(self, connection: IRawConnection) -> None:
        """
        Upgrade and register an incoming raw WebRTC connection with the swarm.
        """
        if self.host is None:
            await connection.close()
            raise WebRTCError("Host not set for incoming WebRTC connection")

        remote_peer_id = getattr(connection, "remote_peer_id", None)
        if remote_peer_id is None:
            await connection.close()
            raise WebRTCError("Incoming WebRTC connection missing remote peer ID")

        network = self.host.get_network()
        if not hasattr(network, "upgrader") or not hasattr(network, "add_conn"):
            await connection.close()
            raise WebRTCError(
                "Host network must expose upgrader/add_conn for WebRTC connections"
            )

        swarm = cast("Swarm", network)
        try:
            secured_conn = await swarm.upgrader.upgrade_security(
                connection, False, remote_peer_id
            )
            muxed_conn = await swarm.upgrader.upgrade_connection(
                secured_conn, remote_peer_id
            )
            await swarm.add_conn(muxed_conn)
            logger.info("Registered incoming WebRTC connection from %s", remote_peer_id)
        except Exception as exc:
            logger.error(
                "Failed to upgrade incoming WebRTC connection from %s: %s",
                remote_peer_id,
                exc,
            )
            try:
                await connection.close()
            except Exception:
                pass
            raise WebRTCError(
                f"Failed to upgrade incoming WebRTC connection: {exc}"
            ) from exc

        conn_id = str(remote_peer_id)
        self.active_connections[conn_id] = connection

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

        if not self._advertised_addrs:
            self._refresh_listener_addresses()

        return list(self._advertised_addrs)

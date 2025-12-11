import logging
from typing import TYPE_CHECKING, Any, cast

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import Multiaddr
import trio
from trio_asyncio import aio_as_trio, open_loop
from trio_typing import TaskStatus

from libp2p.abc import IHost, IListener, IRawConnection, ISecureConn, ITransport
from libp2p.custom_types import THandler
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.nat import ReachabilityChecker
from libp2p.transport.exceptions import OpenConnectionError

from ..constants import (
    DEFAULT_ICE_SERVERS,
    WebRTCError,
)
from ..signal_service import SignalService
from ..udp_hole_punching import UDPHolePuncher
from .connect import connect
from .direct_rtc_connection import DirectPeerConnection
from .gen_certificate import (
    WebRTCCertificate,
    parse_webrtc_maddr,
)
from .listener import WebRTCDirectListener
from .util import (
    canonicalize_certhash,
    extract_certhash,
    fingerprint_to_certhash,
    generate_ice_credentials,
)

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


class WebRTCDirectTransport(ITransport):
    """
    Provides direct peer-to-peer WebRTC connections without signaling servers.
    """

    def __init__(self) -> None:
        """Initialize WebRTC-Direct transport."""
        self.ice_servers = DEFAULT_ICE_SERVERS
        self.active_connections: dict[str, IRawConnection | ISecureConn] = {}
        self.pending_connections: dict[str, RTCPeerConnection] = {}
        self._started = False
        self.host: IHost | None = None
        self.connection_events: dict[str, trio.Event] = {}
        self.cert_mgr: WebRTCCertificate | None = None
        self.udp_puncher = UDPHolePuncher()
        self._renewal_task: trio.CancelScope | None = None
        self.supported_protocols: set[str] = {"webrtc-direct", "p2p"}
        self.signal_service: SignalService | None = None
        # NAT traversal detection
        self._reachability_checker: ReachabilityChecker | None = None
        logger.info("WebRTC-Direct Transport initialized")

    async def start(self, nursery: trio.Nursery) -> None:
        """
        Start the WebRTC-Direct transport.

        Initializes certificate management, NAT detection, signaling service,
        and starts the certificate renewal loop as a background task.

        Args:
            nursery: Trio nursery for spawning background tasks.

        Raises:
            WebRTCError: If host is not set or if critical initialization fails.

        """
        if self._started:
            logger.debug("WebRTC-Direct transport already started")
            return

        if not self.host:
            raise WebRTCError("Host must be set before starting transport")

        # Generate certificate for this transport
        self.cert_mgr = WebRTCCertificate()
        logger.debug(
            f"Generated WebRTC certificate with certhash: {self.cert_mgr.certhash}"
        )

        # FIX #1: Start certificate renewal loop properly with cancellation support
        try:
            self._renewal_task = await nursery.start(self._cert_renewal_task)
            logger.info("Certificate renewal task started with cancellation support")
        except Exception as e:
            logger.error(f"Failed to start certificate renewal task: {e}")
            # Continue gracefully - certificate will still work until expiry
            self._renewal_task = None

        # Initialize signal service
        if self.signal_service is None:
            self.signal_service = SignalService(self.host)

        network = self.host.get_network()
        try:
            await self.signal_service.listen(network, None)
            logger.debug("WebRTC signaling service started")
        except Exception:
            logger.warning("Failed to start WebRTC signaling service", exc_info=True)

        # Initialize NAT reachability checker
        if self.host:
            self._reachability_checker = ReachabilityChecker(self.host)
            logger.debug("NAT reachability checker initialized for WebRTC-Direct")

        self._started = True
        logger.info("WebRTC-Direct Transport started successfully")

    async def stop(self) -> None:
        """
        Stop the WebRTC-Direct transport.

        Performs clean shutdown:
        1. Closes all active and pending connections
        2. Cancels the certificate renewal task
        3. Cleans up NAT detection resources

        This method is designed to be robust and won't raise exceptions
        even if some cleanup operations fail.
        """
        if not self._started:
            logger.debug("WebRTC-Direct transport not started")
            return

        logger.info("Stopping WebRTC-Direct Transport")

        # Clean up connections
        logger.debug(f"Closing {len(self.active_connections)} active connections")
        for conn_id in list(self.active_connections.keys()):
            try:
                await self._cleanup_connection(conn_id)
            except Exception as e:
                logger.warning(f"Error cleaning up connection {conn_id}: {e}")

        # FIX #2: Implement proper task cancellation with timeout protection
        if self._renewal_task is not None:
            logger.debug("Cancelling certificate renewal task")
            try:
                # Cancel the renewal task immediately
                self._renewal_task.cancel()

                # Brief wait for cancellation to propagate and propagate
                # This allows the task to catch trio.Cancelled and cleanup gracefully
                with trio.move_on_after(1) as timeout_scope:
                    # Yield control to scheduler so cancellation propagates
                    await trio.sleep(0)

                if timeout_scope.cancelled_caught:
                    logger.warning(
                        "Certificate renewal task cancellation timed out after 1 second"
                    )
                else:
                    logger.debug("Certificate renewal task cancelled successfully")

            except Exception as e:
                logger.warning(f"Error cancelling renewal task: {e}")
            finally:
                # Always clear the reference
                self._renewal_task = None

        # Clean up NAT detection
        self._reachability_checker = None

        self._started = False
        logger.info("WebRTC-Direct Transport stopped")

    def can_handle(self, maddr: Multiaddr) -> bool:
        """Check if transport can handle the multiaddr."""
        protocols = {p.name for p in maddr.protocols()}
        return bool(protocols.intersection(self.supported_protocols))

    async def dial(self, maddr: Multiaddr) -> IRawConnection | ISecureConn:
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

            ufrag, ice_pwd = generate_ice_credentials()

            if self.cert_mgr is None:
                raise WebRTCError(
                    "Certificate manager not initialised for WebRTC-Direct"
                )
            if self.host is None:
                raise WebRTCError("Transport host must be set before dialing")

            # Store peer address in peerstore before dialing
            # This is required for signal_service to create streams to the peer
            peerstore = self.host.get_peerstore()
            try:
                # Extract base address (without webrtc-direct and p2p components)
                ip_proto = "ip6" if ":" in ip else "ip4"
                base_addr = Multiaddr(f"/{ip_proto}/{ip}/udp/{port}")
                peerstore.add_addr(peer_id, base_addr, 3600)
                logger.debug(f"Stored peer address {base_addr} for {peer_id}")
            except Exception as e:
                logger.debug(f"Failed to store peer address in peerstore: {e}")
                # Continue anyway - might already be stored

            # NAT detection: Check peer and self-reachability
            is_peer_reachable = False
            is_self_reachable = False
            public_addrs_self: list[Multiaddr] = []

            if self._reachability_checker:
                try:
                    # Check peer reachability
                    is_peer_reachable = (
                        await self._reachability_checker.check_peer_reachability(
                            peer_id
                        )
                    )
                    logger.debug(f"Peer {peer_id} reachable: {is_peer_reachable}")

                    # Check self-reachability
                    (
                        is_self_reachable,
                        public_addrs_self,
                    ) = await self._reachability_checker.check_self_reachability()
                    logger.debug(
                        f"Self reachable: {is_self_reachable}, "
                        f"public addresses: {len(public_addrs_self)}"
                    )
                except Exception as nat_exc:
                    logger.debug(f"NAT detection check failed: {nat_exc}")
                    # Continue with conservative approach (assume NAT)

            # Determine if UDP hole punching is needed
            needs_hole_punching = not (is_peer_reachable and is_self_reachable)

            punch_metadata = {
                "ufrag": ufrag,
                "peer_id": str(self.host.get_id()),
                "certhash": self.cert_mgr.certhash,
                "fingerprint": self.cert_mgr.fingerprint,
                "role": "client",
            }
            logger.warning(
                "Dialer using certificate fingerprint=%s certhash=%s",
                self.cert_mgr.fingerprint,
                self.cert_mgr.certhash,
            )

            # Attempt UDP hole punching only when needed
            hole_punch_success = False
            if needs_hole_punching:
                logger.debug(
                    f"Attempting UDP punching (peer reachable: {is_peer_reachable}, "
                    f"self reachable: {is_self_reachable})"
                )
                print(f"UDP punch toward {ip}:{port} with metadata {punch_metadata}")
                try:
                    await self.udp_puncher.punch_hole(ip, port, punch_metadata)
                    hole_punch_success = True
                    await trio.sleep(0.2)
                except Exception as punch_exc:
                    logger.warning(
                        "UDP hole punching failed prior to dialing: %s", punch_exc
                    )
                    # Will fallback to Circuit Relay v2 if both peers behind NAT
            else:
                logger.debug("Both peers appear reachable, skipping UDP hole punching")

            # Configure ICE servers based on NAT status
            ice_servers_dict: list[dict[str, str]] = []
            if not is_self_reachable:
                # Behind NAT - use STUN/TURN servers
                ice_servers_dict = DEFAULT_ICE_SERVERS
                logger.debug("Configured ICE servers for NAT traversal")
            else:
                # Public IP - minimal ICE servers (STUN only for discovery)
                ice_servers_dict = (
                    [{"urls": "stun:stun.l.google.com:19302"}]
                    if DEFAULT_ICE_SERVERS
                    else []
                )
                logger.debug("Configured minimal ICE servers for public IP")

            # Convert dict list to RTCIceServer list
            rtc_ice_servers = [
                RTCIceServer(**s) if not isinstance(s, RTCIceServer) else s
                for s in ice_servers_dict
            ]

            async with open_loop():
                conn_id = str(peer_id)
                rtc_config = RTCConfiguration(iceServers=rtc_ice_servers)
                direct_peer_connection = (
                    await DirectPeerConnection.create_dialer_rtc_peer_connection(
                        role="client",
                        ufrag=ufrag,
                        ice_pwd=ice_pwd,
                        rtc_configuration=rtc_config,
                        certificate=self.cert_mgr,
                    )
                )

                try:
                    swarm = cast("Swarm", self.host.get_network())
                    if self.signal_service is None:
                        raise WebRTCError(
                            "Signal service not available for WebRTC-Direct dialing"
                        )

                    async def handle_offer(
                        offer_desc: RTCSessionDescription, handler_ufrag: str
                    ) -> RTCSessionDescription:
                        return await self._exchange_offer_answer_direct(
                            peer_id,
                            offer_desc,
                            certhash or "",
                            {"ufrag": handler_ufrag},
                        )

                    secure_conn, _ = await connect(
                        role="client",
                        ufrag=ufrag,
                        ice_pwd=ice_pwd,
                        peer_connection=direct_peer_connection,
                        remote_addr=maddr,
                        remote_peer_id=peer_id,
                        signal_service=self.signal_service,
                        certhash=certhash,
                        offer_handler=handle_offer,
                        security_multistream=swarm.upgrader.security_multistream,
                    )
                    if secure_conn is None:
                        raise OpenConnectionError("WebRTC-Direct connection failed")
                    remote_fp = getattr(secure_conn, "remote_fingerprint", None)
                    expected_certhash = None
                    try:
                        expected_certhash = extract_certhash(maddr)
                    except Exception:
                        expected_certhash = None
                    actual_certhash = None
                    if remote_fp:
                        try:
                            actual_certhash = fingerprint_to_certhash(remote_fp)
                        except Exception:
                            actual_certhash = None
                    if expected_certhash and actual_certhash:
                        if expected_certhash != actual_certhash:
                            await secure_conn.close()
                            raise OpenConnectionError(
                                "Remote certhash mismatch detected during dial"
                            )
                    canonical_remote = (
                        canonicalize_certhash(maddr, actual_certhash)
                        if actual_certhash
                        else maddr
                    )
                    setattr(secure_conn, "remote_multiaddr", canonical_remote)
                    if self.cert_mgr is not None and self.host is not None:
                        local_peer = self.host.get_id()
                        local_ma = Multiaddr(
                            f"/certhash/{self.cert_mgr.certhash}/p2p/{local_peer}"
                        )
                        setattr(secure_conn, "local_multiaddr", local_ma)
                        if getattr(secure_conn, "local_fingerprint", None) is None:
                            setattr(
                                secure_conn,
                                "local_fingerprint",
                                self.cert_mgr.fingerprint,
                            )
                    if self.host is not None:
                        try:
                            self.host.get_peerstore().add_addrs(
                                peer_id,
                                [canonical_remote],
                                3600,
                            )
                        except Exception:
                            logger.debug(
                                "Failed to persist WebRTC-Direct remote address for %s",
                                peer_id,
                            )
                    self.active_connections[conn_id] = secure_conn
                    self.pending_connections.pop(conn_id, None)
                    self.connection_events.pop(conn_id, None)

                    logger.debug(
                        f"Successfully established WebRTC-direct connection to{peer_id}"
                    )
                    return secure_conn
                except Exception as e:
                    logger.error(f"Failed to connect as client: {e}")
                    # Close peer connection with async compatibility handling
                    try:
                        await aio_as_trio(direct_peer_connection.close())
                    except Exception as close_err:
                        logger.warning(
                            f"Error closing peer connection during cleanup: {close_err}"
                        )

                    # Fallback to Circuit Relay v2 if both peers behind NAT
                    #  and UDP hole punching failed
                    if (
                        not is_self_reachable
                        and not is_peer_reachable
                        and not hole_punch_success
                        and self._reachability_checker
                    ):
                        logger.info(
                            "UDP hole punching failed for NAT peers, "
                            "attempting Circuit Relay v2 fallback"
                        )
                        try:
                            return await self._dial_via_relay_fallback(maddr, peer_id)
                        except Exception as relay_exc:
                            logger.warning(
                                f"Circuit Relay v2 fallback also failed: {relay_exc}"
                            )
                            # Continue to raise original error

                    raise OpenConnectionError(
                        f"Failed to connect as client: {e}"
                    ) from e

        except Exception as e:
            logger.error(f"Failed to dial WebRTC-Direct connection to {maddr}: {e}")
            raise OpenConnectionError(f"WebRTC-Direct dial failed: {e}") from e

    def create_listener(self, handler_function: THandler | None = None) -> IListener:
        """Create a WebRTC-Direct listener for incoming connections."""
        if self.cert_mgr is None:
            raise OpenConnectionError("Cert_mgr not present")

        # Configure ICE servers for the listener (server side)
        # Use default ICE servers for NAT traversal support
        rtc_ice_servers = [
            RTCIceServer(**s) if not isinstance(s, RTCIceServer) else s
            for s in self.ice_servers
        ]
        rtc_config = RTCConfiguration(iceServers=rtc_ice_servers)

        listener = WebRTCDirectListener(
            transport=self,
            cert=self.cert_mgr,
            rtc_configuration=rtc_config,
            signal_service=self.signal_service,
        )
        return listener

    async def register_incoming_connection(
        self, connection: IRawConnection | ISecureConn
    ) -> None:
        """Register an incoming connection from the listener."""
        if self.host is None:
            await connection.close()
            return

        remote_peer_id = getattr(connection, "remote_peer_id", None)
        if remote_peer_id is None:
            await connection.close()
            raise WebRTCError("Incoming WebRTC-Direct conn: missing remote peer ID")

        network = self.host.get_network()
        if not hasattr(network, "upgrader") or not hasattr(network, "add_conn"):
            await connection.close()
            raise WebRTCError(
                "Host network does not expose upgrader/add_conn required for WebRTC"
            )

        swarm = cast("Swarm", network)

        try:
            if isinstance(connection, ISecureConn):
                secured_conn = connection
            else:
                secured_conn = await swarm.upgrader.upgrade_security(
                    connection, False, remote_peer_id
                )
            muxed_conn = await swarm.upgrader.upgrade_connection(
                secured_conn, remote_peer_id
            )
            await swarm.add_conn(muxed_conn)
            logger.info(
                "Registered incoming WebRTC-Direct connection from %s", remote_peer_id
            )
        except Exception as exc:
            logger.error(
                "Failed to upgrade incoming WebRTC-Direct connection from %s: %s",
                remote_peer_id,
                exc,
            )
            try:
                await connection.close()
            except Exception:
                pass
            raise WebRTCError(
                f"Failed to upgrade incoming WebRTC-Direct connection: {exc}"
            ) from exc

        conn_id = str(remote_peer_id)
        self.pending_connections.pop(conn_id, None)
        self.active_connections[conn_id] = secured_conn

        event = self.connection_events.get(conn_id)
        if event is not None:
            event.set()

    async def _exchange_offer_answer_direct(
        self,
        peer_id: ID,
        offer: RTCSessionDescription,
        certhash: str,
        extra: dict[str, Any] | None = None,
    ) -> RTCSessionDescription:
        """Exchange offer/answer over the configured signaling service."""
        if self.signal_service is None:
            raise WebRTCError("Signal service not configured for WebRTC-Direct")

        payload = extra.copy() if extra else {}
        logger.debug(
            "Exchanging WebRTC-Direct offer with %s via signal service", peer_id
        )
        return await self.signal_service.negotiate_connection(
            peer_id, offer, certhash, payload
        )

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

    async def _dial_via_relay_fallback(
        self, maddr: Multiaddr, peer_id: ID
    ) -> IRawConnection:
        """
        Fallback to Circuit Relay v2 when UDP hole punching fails.

        This method uses the private-to-private WebRTC transport as a fallback
        when both peers are behind NAT and direct connection fails.
        """
        logger.info(f"Attempting Circuit Relay v2 fallback for {peer_id}")

        # Import here to avoid circular dependency
        from ..private_to_private.transport import WebRTCTransport

        # Create a temporary private-to-private transport instance
        if self.host is None:
            raise WebRTCError("Host must be set for Circuit Relay v2 fallback")

        relay_transport = WebRTCTransport({})
        relay_transport.set_host(self.host)

        try:
            # Start the relay transport
            await relay_transport.start()

            # Try to find a relay address for the peer
            peerstore = self.host.get_peerstore() if self.host else None
            if peerstore:
                # Look for existing relay addresses
                relay_addrs = peerstore.addrs(peer_id)
                for relay_addr in relay_addrs:
                    if "/p2p-circuit" in str(relay_addr):
                        # Found a relay address, use it
                        relay_maddr = relay_addr.encapsulate(
                            Multiaddr(f"/webrtc/p2p/{peer_id.to_base58()}")
                        )
                        logger.debug(f"Using existing relay address: {relay_maddr}")
                        return await relay_transport.dial(relay_maddr)

            # If no relay address found, we can't proceed with fallback
            raise OpenConnectionError(
                f"No relay addr available for {peer_id} for relay fallback"
            )

        finally:
            try:
                await relay_transport.stop()
            except Exception:
                pass

    async def _cert_renewal_task(
        self,
        *,
        task_status: TaskStatus[trio.CancelScope] = trio.TASK_STATUS_IGNORED,
    ) -> None:
        """
        Certificate renewal task with trio cancellation support.

        This method wraps the actual renewal loop and returns a CancelScope
        that allows the task to be cancelled on demand during transport shutdown.

        The task_status.started() pattern allows nursery.start() to return
        a CancelScope immediately, enabling fine-grained control over the task.

        Args:
            task_status: Trio task status object for signaling task startup.

        Raises:
            trio.Cancelled: When the renewal task is cancelled during shutdown.

        """
        with trio.CancelScope() as cancel_scope:
            # Signal that the task has started and return the CancelScope
            task_status.started(cancel_scope)

            try:
                logger.debug("Certificate renewal task started")
                # Delegate to the actual renewal loop from cert_mgr
                if self.cert_mgr is None:
                    raise WebRTCError("Certificate manager not initialized")
                await self.cert_mgr.renewal_loop()
            except trio.Cancelled:
                logger.debug("Certificate renewal task cancelled gracefully")
                raise
            except Exception as e:
                logger.error(f"Certificate renewal task error: {e}", exc_info=True)
                raise

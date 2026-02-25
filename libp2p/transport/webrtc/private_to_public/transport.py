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
from trio_typing import TaskStatus

from libp2p.abc import IHost, IListener, IRawConnection, ISecureConn, ITransport
from libp2p.custom_types import THandler
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.nat import ReachabilityChecker
from libp2p.transport.exceptions import OpenConnectionError

from ..async_bridge import get_webrtc_bridge
from ..constants import (
    DEFAULT_DIAL_TIMEOUT,
    DEFAULT_ICE_SERVERS,
    MUXER_NEGOTIATE_TIMEOUT,
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
    is_localhost_address,
)

try:
    from libp2p.transport.webrtc.aiortc_patch import (
        register_upgrade,
        unregister_upgrade,
    )
except Exception:  # pragma: no cover

    def register_upgrade(_: Any) -> None:  # type: ignore[misc]
        return

    def unregister_upgrade(_: Any) -> None:  # type: ignore[misc]
        return


if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


# Import ICE configuration fixes
try:
    from ..ice_config_fix import (
        create_ice_config_for_address,
        enhanced_aioice_localhost_patch,
    )

    # Apply aioice localhost patch at module import
    if enhanced_aioice_localhost_patch is not None:
        try:
            enhanced_aioice_localhost_patch()
            logger.info("Enhanced aioice localhost patch applied")
        except Exception as e:
            logger.warning(f"Failed to apply aioice localhost patch: {e}")
except ImportError:
    # Fallback if module not available
    create_ice_config_for_address = None
    enhanced_aioice_localhost_patch = None
    logger.warning("ICE config fixes not available - using default configuration")


# NOTE: _verify_data_channel_open() removed - Noise now owns the DataChannel
# If Noise handshake succeeded, the transport is already real and wired correctly.


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
        self.secure_conn: ISecureConn | None = None
        self.libp2p_owner_ready = trio.Event()
        # Store nursery for background tasks
        self._nursery: trio.Nursery | None = None
        self._loop_holder_stop = trio.Event()
        self._loop_ready = trio.Event()
        self._loop_holder_exited = trio.Event()
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

        self._nursery = nursery
        self._loop_holder_stop = trio.Event()
        self._loop_ready = trio.Event()
        self._loop_holder_exited = trio.Event()

        self._nursery.start_soon(self._hold_loop_open)
        await self._loop_ready.wait()
        logger.info("WebRTC asyncio loop held open for transport lifetime")

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

        self._loop_holder_stop.set()
        with trio.move_on_after(2.0):
            await self._loop_holder_exited.wait()

        self._started = False
        logger.info("WebRTC-Direct Transport stopped")

    async def _hold_loop_open(self) -> None:
        """Keep asyncio loop open so aiortc/aioice run in a stable context."""
        bridge = get_webrtc_bridge()
        async with bridge:
            self._loop_ready.set()
            try:
                await self._loop_holder_stop.wait()
            finally:
                self._loop_holder_exited.set()

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
                # For localhost, ensure TCP addresses are available for signaling
                # Signal service needs TCP connection,
                # This prevents recursion when signal_service tries to create a stream
                if is_localhost_address(ip):
                    try:
                        network = self.host.get_network()
                        existing_connections = (
                            network.get_connections(peer_id)
                            if hasattr(network, "get_connections")
                            else []
                        )
                        try:
                            existing_addrs = peerstore.addrs(peer_id)
                        except Exception:
                            existing_addrs = []
                        tcp_addrs = [
                            a
                            for a in existing_addrs
                            if "/tcp/" in str(a) and "/webrtc" not in str(a)
                        ]
                        if not existing_connections and not tcp_addrs:
                            logger.debug(
                                f"No TCP addr for {peer_id} on localhost - "
                                "signal_service will handle this"
                            )
                    except Exception as tcp_exc:
                        logger.debug(
                            f"Error checking TCP addresses for localhost: {tcp_exc}"
                        )
            except Exception as e:
                logger.debug(f"Failed to store peer address in peerstore: {e}")
                # Continue anyway - might already be stored

            # Check if this is a localhost connection -
            # skip NAT checks and UDP hole punching
            is_localhost = is_localhost_address(ip)
            public_addrs_self: list[Multiaddr] = []
            if is_localhost:
                logger.debug(
                    f"Localhost connection detected ({ip}), "
                    "skipping NAT checks and UDP hole punching"
                )
                is_peer_reachable = True
                is_self_reachable = True
                needs_hole_punching = False
            else:
                # NAT detection: Check peer and self-reachability
                is_peer_reachable = False
                is_self_reachable = False

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
            # For private-to-public, we also use the punch socket as a lightweight
            # UDP signaling path for offer/answer (avoids requiring a TCP addr).
            if needs_hole_punching or is_localhost:
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

            # CRITICAL FIX: Use optimized ICE configuration based on target address
            # This ensures localhost connections work properly without ICE servers
            # and remote connections get appropriate STUN/TURN configuration
            if create_ice_config_for_address is not None:
                rtc_config = create_ice_config_for_address(ip)
                logger.info(
                    f"Using optimized ICE configuration for {ip} "
                    f"(localhost={is_localhost})"
                )
            else:
                # Fallback to original logic if ICE config fix not available
                ice_servers_dict: list[dict[str, str]] = []
                if is_localhost:
                    # Localhost - no ICE servers needed
                    ice_servers_dict = []
                    logger.debug("Localhost connection - no ICE servers needed")
                elif not is_self_reachable:
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
                rtc_config = RTCConfiguration(iceServers=rtc_ice_servers)

            # Loop managed at Transport level (no local open_loop);
            #  persistent loop avoids SCTP freeze.
            conn_id = str(peer_id)
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
                swarm = cast("Swarm", self.host.get_network())
                if self.signal_service is None:
                    raise WebRTCError(
                        "Signal service not available for WebRTC-Direct dialing"
                    )

                async def handle_offer(
                    offer_desc: RTCSessionDescription, handler_ufrag: str
                ) -> RTCSessionDescription:
                    payload = {
                        "type": "offer",
                        "ufrag": handler_ufrag,
                        "sdp": offer_desc.sdp,
                        "sdpType": offer_desc.type,
                        "certhash": certhash or "",
                        "peer_id": str(self.host.get_id()) if self.host else "",
                    }
                    await self.udp_puncher.send_json(ip, port, payload)
                    resp = await self.udp_puncher.recv_json(
                        ip, port, timeout_s=DEFAULT_DIAL_TIMEOUT
                    )
                    if resp is None or resp.get("type") != "answer":
                        raise OpenConnectionError(
                            "No UDP answer received for WebRTC-Direct offer"
                        )
                    answer_desc = RTCSessionDescription(
                        sdp=resp.get("sdp", ""), type=resp.get("sdpType", "answer")
                    )
                    return answer_desc

                connection_timeout = DEFAULT_DIAL_TIMEOUT
                secure_conn = None
                connection_error = None

                with trio.move_on_after(connection_timeout) as timeout_scope:
                    try:
                        secure_conn, _ = await connect(
                            role="client",
                            ufrag=ufrag,
                            ice_pwd=ice_pwd,
                            peer_connection=direct_peer_connection,
                            remote_addr=maddr,
                            remote_peer_id=peer_id,
                            signal_service=None,
                            certhash=certhash,
                            offer_handler=handle_offer,
                            security_multistream=swarm.upgrader.security_multistream,
                        )
                        # CRITICAL: Data pump is already running
                        # wait for it to be ready if needed
                        if hasattr(secure_conn, "_buffer_consumer_ready"):
                            with trio.move_on_after(0.5) as timeout_scope:
                                await secure_conn._buffer_consumer_ready.wait()
                            if timeout_scope.cancelled_caught:
                                logger.debug(
                                    "Data pump ready timeout for %s, proceeding anyway",
                                    peer_id,
                                )
                        logger.debug(
                            f"[DEBUG] About to call upgrade_connection() for {peer_id}"
                        )
                    except Exception as connect_exc:
                        connection_error = connect_exc
                        if not timeout_scope.cancelled_caught:
                            raise

                # Check if connection timed out
                if timeout_scope.cancelled_caught or secure_conn is None:
                    # Close peer connection on timeout
                    try:
                        bridge = get_webrtc_bridge()
                        async with bridge:
                            await bridge.close_peer_connection(direct_peer_connection)
                    except Exception:
                        pass
                    # Trigger fallback if both peers behind NAT
                    if (
                        not is_localhost
                        and not is_self_reachable
                        and not is_peer_reachable
                        and self._reachability_checker
                    ):
                        logger.info(
                            f"Direct conn timed out after {connection_timeout}s "
                            "for NAT peers, attempting Circuit Relay v2 fallback"
                        )
                        try:
                            return await self._dial_via_relay_fallback(maddr, peer_id)
                        except Exception as relay_exc:
                            logger.warning(f"Relay fallback failed: {relay_exc}")
                    # Raise timeout error
                    raise OpenConnectionError(
                        f"WebRTC-Direct conn timed out after {connection_timeout}s"
                    ) from connection_error

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
                    f"Successfully established WebRTC-direct connection to {peer_id}"
                )
                # CRITICAL: Dialer owns the upgrade lifecycle.
                # The dialer initiates muxer negotiation and registers with swarm.
                # The listener waits and responds to the dialer's negotiation.

                # Get peer connection and raw connection for ownership event
                pc = getattr(secure_conn, "_webrtc_peer_connection", None)
                raw_conn = None
                try:
                    # Try to access underlying raw connection
                    if hasattr(secure_conn, "conn"):
                        conn_wrapper = secure_conn.conn
                        if hasattr(conn_wrapper, "read_writer"):
                            read_writer = conn_wrapper.read_writer
                            if hasattr(read_writer, "read_writer"):
                                raw_conn = read_writer.read_writer
                except Exception:
                    pass

                try:
                    # Get raw connection for diagnostic logging
                    raw_conn_check = None
                    try:
                        if hasattr(secure_conn, "conn"):
                            conn_wrapper = secure_conn.conn
                            if hasattr(conn_wrapper, "read_writer"):
                                read_writer = conn_wrapper.read_writer
                                if hasattr(read_writer, "read_writer"):
                                    raw_conn_check = read_writer.read_writer
                    except Exception:
                        pass

                    raw_is_initiator = (
                        getattr(raw_conn_check, "is_initiator", None)
                        if raw_conn_check
                        else None
                    )
                    secure_is_initiator = getattr(secure_conn, "is_initiator", None)

                    raw_typ = (
                        type(raw_conn_check).__name__ if raw_conn_check else "None"
                    )
                    logger.info(
                        "Before muxer: peer=%s raw_init=%s sec_init=%s "
                        "raw_typ=%s sec_typ=%s",
                        peer_id,
                        raw_is_initiator,
                        secure_is_initiator,
                        raw_typ,
                        type(secure_conn).__name__,
                    )

                    # CRITICAL: Validate read loop is active before muxer negotiation
                    # The buffer consumer must be running to forward messages from
                    # early handler buffer to receive_channel, which read() consumes
                    if raw_conn_check is not None:
                        has_buffer = hasattr(raw_conn_check, "_incoming_message_buffer")
                        buffer_active = (
                            raw_conn_check._incoming_message_buffer is not None
                            if has_buffer
                            else False
                        )
                        ch_state = getattr(
                            raw_conn_check.data_channel, "readyState", "unknown"
                        )
                        logger.info(
                            "Read loop validation peer=%s buf=%s active=%s ch=%s",
                            peer_id,
                            has_buffer,
                            buffer_active,
                            ch_state,
                        )

                        # Wait for buffer consumer before muxer so msgs flow to read().
                        if buffer_active:
                            if hasattr(raw_conn_check, "_buffer_consumer_ready"):
                                logger.info(
                                    "Waiting for buffer consumer ready for %s", peer_id
                                )
                                # Wait with timeout to avoid infinite wait
                                # Increased from 2.0s to 5.0s to give the data
                                # pump system task more time to start under load
                                with trio.move_on_after(5.0) as timeout_scope:
                                    await raw_conn_check._buffer_consumer_ready.wait()

                                if timeout_scope.cancelled_caught:
                                    logger.warning(
                                        "Buffer consumer ready timeout %s,"
                                        " proceeding anyway",
                                        peer_id,
                                    )
                                else:
                                    logger.info(
                                        "Buffer consumer ready %s,"
                                        " msgs flow to receive_channel",
                                        peer_id,
                                    )
                            else:
                                # No ready event - give consumer a moment to start
                                await trio.sleep(0.2)
                                logger.info(
                                    "Buffer consumer running for %s (sleep fallback)",
                                    peer_id,
                                )

                    print(
                        f"[webrtc-direct] dialer muxer negotiation: peer={peer_id} "
                        f"is_initiator={secure_is_initiator}"
                    )

                    # Dialer initiates muxer negotiation (is_initiator=True)
                    # Listener will respond automatically when it receives
                    # the protocol select message
                    logger.info(
                        f"🟢 Calling upgrade_connection() for peer={peer_id} - "
                        f"muxer negotiation will start now (read loop should be active)"
                    )
                    print(f"[DEBUG] About to call upgrade_connection() for {peer_id}")

                    # CRITICAL: Register upgrade protection before muxer negotiation
                    if pc is not None:
                        register_upgrade(pc)
                        logger.debug(
                            f"Upgrade protection confirmed active for {peer_id}"
                        )

                    # Add timeout wrapper to detect hangs
                    import traceback

                    stack_str = "".join(traceback.format_stack()[-5:])
                    print(f"[DEBUG] Stack before upgrade_connection:\n{stack_str}")

                    try:
                        with trio.fail_after(MUXER_NEGOTIATE_TIMEOUT):
                            muxed_conn = await swarm.upgrader.upgrade_connection(
                                cast(ISecureConn, secure_conn), peer_id
                            )
                        print(f"[DEBUG] upgrade_connection() returned for {peer_id}")
                        logger.info(
                            f"✅ upgrade_connection() completed for {peer_id}, "
                            f"muxed_conn type: {type(muxed_conn).__name__}"
                        )
                    except trio.TooSlowError as muxer_timeout_exc:
                        logger.error(
                            "Muxer negotiation timed out after %.1fs "
                            "for peer=%s. This usually means the remote "
                            "side did not start its muxer negotiation, "
                            "or the data channel pipeline is stalled.",
                            MUXER_NEGOTIATE_TIMEOUT,
                            peer_id,
                        )
                        raise OpenConnectionError(
                            f"Muxer negotiation timed out after "
                            f"{MUXER_NEGOTIATE_TIMEOUT}s for {peer_id}. "
                            f"Check that both peers are running compatible "
                            f"muxer protocols and data channels are flowing."
                        ) from muxer_timeout_exc
                    except Exception as upgrade_inner_exc:
                        print("[DEBUG] upgrade_connection() raised:", upgrade_inner_exc)
                        logger.error(
                            "upgrade_connection() failed for %s: %s",
                            peer_id,
                            upgrade_inner_exc,
                            exc_info=True,
                        )
                        raise

                    # Register the muxed connection with swarm
                    await swarm.add_conn(muxed_conn)

                    # CRITICAL: Unregister upgrade protection
                    #  AFTER muxer negotiation + swarm.add_conn
                    # Ownership event will be set next, which provides final protection
                    if pc is not None:
                        unregister_upgrade(pc)
                        logger.debug(
                            f"Upgrade protection unregistered for {peer_id} "
                            "(muxer + swarm.add_conn complete)"
                        )

                    # Set ownership event ONLY here, after all three conditions:
                    # 1. muxer negotiation finished (upgrade_connection returned)
                    # 2. Noise session established
                    # (already done before upgrade_connection)
                    # 3. swarm.add_conn(conn) returned successfully
                    if raw_conn is not None and hasattr(raw_conn, "libp2p_owner_ready"):
                        raw_conn.libp2p_owner_ready.set()
                        logger.info(
                            f"✅ Ownership event SET for {peer_id} - "
                            f"libp2p now owns connection lifecycle"
                        )
                    # Also store event reference on peer connection for aiortc patches
                    if pc is not None and raw_conn is not None:
                        if hasattr(raw_conn, "libp2p_owner_ready"):
                            setattr(
                                pc,
                                "_libp2p_owner_ready_event",
                                raw_conn.libp2p_owner_ready,
                            )

                    # Note: The event should be set immediately
                    # after swarm.add_conn() succeeds,
                    #  so this should never timeout.
                    if raw_conn is not None and hasattr(raw_conn, "libp2p_owner_ready"):
                        if not raw_conn.libp2p_owner_ready.is_set():
                            raise RuntimeError(
                                "libp2p ownership not set after swarm.add_conn(); "
                                "bug in ownership transfer"
                            )

                    logger.info(
                        "Dialer completed muxer negotiation and registered connection "
                        "with swarm: peer=%s (ownership transferred to libp2p)",
                        peer_id,
                    )
                except Exception as upgrade_exc:
                    logger.error(
                        "Dialer failed to upgrade/register WebRTC-Direct conn: %s",
                        upgrade_exc,
                        exc_info=True,
                    )
                    # Unregister upgrade protection on failure
                    if pc is not None:
                        unregister_upgrade(pc)
                    try:
                        await secure_conn.close()
                    except Exception:
                        pass
                    raise OpenConnectionError(
                        f"Failed to upgrade/register WebRTC-Direct conn: {upgrade_exc}"
                    ) from upgrade_exc
                return secure_conn
            except trio.TooSlowError as exc:
                logger.error(f"WebRTC-Direct dial timed out: {exc}")
                # Close peer connection with async compatibility handling
                try:
                    bridge = get_webrtc_bridge()
                    async with bridge:
                        await bridge.close_peer_connection(direct_peer_connection)
                except Exception as close_err:
                    logger.warning(
                        f"Error closing peer connection during cleanup: {close_err}"
                    )
                raise OpenConnectionError(
                    f"WebRTC-Direct conn timed out after {connection_timeout}s"
                ) from exc
            except Exception as exc:
                logger.error(f"Failed to connect as client: {exc}")
                # Close peer connection with async compatibility handling
                try:
                    bridge = get_webrtc_bridge()
                    async with bridge:
                        await bridge.close_peer_connection(direct_peer_connection)
                except Exception as close_err:
                    logger.warning(
                        f"Error closing peer connection during cleanup: {close_err}"
                    )

                # Fallback to Circuit Relay v2 if both peers behind NAT
                #  and UDP hole punching failed
                if (
                    not is_localhost
                    and not is_self_reachable
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

                raise OpenConnectionError(f"WebRTC-Direct dial failed: {exc}") from exc

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
        """
        Register an incoming connection from the listener.

        CRITICAL: The listener MUST call upgrade_connection() to start reading
        for multistream negotiation. The listener reads first (is_initiator=False),
        while the dialer writes first (is_initiator=True).
        """
        print("[LISTENER] register_incoming_connection() called")
        if self.host is None:
            await connection.close()
            return

        remote_peer_id = getattr(connection, "remote_peer_id", None)
        print(f"[LISTENER] remote_peer_id={remote_peer_id}")
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

            # CRITICAL: Verify is_initiator is False on listener side
            # The listener must read first (responder role)
            # while dialer writes first (initiator role)
            secured_conn_is_initiator = getattr(secured_conn, "is_initiator", None)
            if secured_conn_is_initiator is None:
                setattr(secured_conn, "is_initiator", False)
                secured_conn_is_initiator = False
                logger.info(
                    "Listener: Set is_initiator=False on secured connection for %s",
                    remote_peer_id,
                )

            if secured_conn_is_initiator:
                logger.warning(
                    "Listener: secured_conn.is_initiator is True (expected False) "
                    "for %s - this may cause negotiation conflicts",
                    remote_peer_id,
                )

            logger.info(
                "Listener registered incoming WebRTC-Direct connection from %s "
                "(is_initiator=%s - will READ first, waiting for dialer to WRITE)",
                remote_peer_id,
                secured_conn_is_initiator,
            )

        except Exception as exc:
            logger.error(
                "Failed to register incoming WebRTC-Direct connection from %s: %s",
                remote_peer_id,
                exc,
            )
            try:
                await connection.close()
            except Exception:
                pass
            raise WebRTCError(
                f"Failed to register incoming WebRTC-Direct conn: {exc}"
            ) from exc

        conn_id = str(remote_peer_id)
        self.pending_connections.pop(conn_id, None)
        self.active_connections[conn_id] = secured_conn

        # CRITICAL: Listener MUST call upgrade_connection() to start the responder
        # path (reads first, waits for dialer to write). The listener has
        # is_initiator=False, so it uses multiselect.negotiate() which READS first,
        # then responds. This is different from the dialer which WRITES first.
        #
        # We start this in a background task so it doesn't block, and the responder
        # path will naturally wait for the dialer to write the handshake.
        logger.info(
            "🟢 Listener starting muxer negotiation for %s "
            "(is_initiator=False, will READ first, waiting for dialer to WRITE)",
            remote_peer_id,
        )

        async def listener_upgrade_task() -> None:
            """Background task to handle listener's muxer negotiation."""
            try:
                # Get peer connection for upgrade protection
                pc = getattr(secured_conn, "_webrtc_peer_connection", None)
                if pc is not None:
                    register_upgrade(pc)
                    logger.debug(
                        f"Listener: Upgrade protection registered for {remote_peer_id}"
                    )

                # CRITICAL FIX: Ensure read loop is active before muxer negotiation
                # Get raw connection to check buffer consumer status
                raw_conn_check = None
                try:
                    if hasattr(secured_conn, "conn"):
                        conn_wrapper = secured_conn.conn
                        if hasattr(conn_wrapper, "read_writer"):
                            read_writer = conn_wrapper.read_writer
                            if hasattr(read_writer, "read_writer"):
                                raw_conn_check = read_writer.read_writer
                except Exception:
                    pass

                # Wait for buffer consumer to be ready before starting muxer negotiation
                if raw_conn_check is not None:
                    if hasattr(raw_conn_check, "_buffer_consumer_ready"):
                        logger.info(
                            f"🔵 Listener waiting for buffer consumer "
                            f"to be ready for {remote_peer_id}..."
                        )
                        with trio.move_on_after(5.0) as timeout_scope:
                            await raw_conn_check._buffer_consumer_ready.wait()

                        if timeout_scope.cancelled_caught:
                            logger.warning(
                                f"⚠️ Listener buffer consumer ready timeout "
                                f"for {remote_peer_id} - "
                                "proceeding anyway (consumer may still start)"
                            )
                        else:
                            logger.info(
                                f"✅Listener buffer ready for {remote_peer_id} - "
                                "messages will flow correctly"
                            )

                logger.info(
                    "🟢 Listener calling upgrade_connection() for %s "
                    "(responder path: will READ first, waiting for dialer)",
                    remote_peer_id,
                )
                with trio.fail_after(MUXER_NEGOTIATE_TIMEOUT):
                    muxed_conn = await swarm.upgrader.upgrade_connection(
                        secured_conn, remote_peer_id
                    )

                # CRITICAL FIX: Set ownership event
                # ONLY AFTER muxer negotiation completes
                # This matches the dialer pattern and
                #  ensures proper lifecycle management
                if hasattr(secured_conn, "libp2p_owner_ready"):
                    secured_conn.libp2p_owner_ready.set()
                    logger.info(
                        f"✅ Listener ownership event SET for {remote_peer_id} - "
                        "libp2p now owns connection lifecycle"
                    )

                # Unregister upgrade protection after muxer negotiation completes
                if pc is not None:
                    unregister_upgrade(pc)
                    logger.debug(f"Listener: Upgrade unregistered for {remote_peer_id}")
                logger.info(
                    "✅ Listener completed muxer for %s (muxed_conn type: %s)",
                    remote_peer_id,
                    type(muxed_conn).__name__,
                )

                logger.info(
                    "🟢 Listener registering muxed conn with swarm for %s",
                    remote_peer_id,
                )
                await swarm.add_conn(muxed_conn)
                logger.info(
                    "✅ Listener swarm.add_conn() completed for %s - "
                    "stream accept loop is now running",
                    remote_peer_id,
                )
            except trio.TooSlowError:
                logger.error(
                    "Listener muxer negotiation timed out after %.1fs "
                    "for %s. The dialer may not have started its "
                    "muxer negotiation, or the data channel pipeline "
                    "is stalled.",
                    MUXER_NEGOTIATE_TIMEOUT,
                    remote_peer_id,
                )
                pc = getattr(secured_conn, "_webrtc_peer_connection", None)
                if pc is not None:
                    unregister_upgrade(pc)
            except Exception as listener_upgrade_exc:
                logger.error(
                    "Listener failed to upgrade connection for %s: %s",
                    remote_peer_id,
                    listener_upgrade_exc,
                    exc_info=True,
                )
                # Unregister upgrade protection on failure
                pc = getattr(secured_conn, "_webrtc_peer_connection", None)
                if pc is not None:
                    unregister_upgrade(pc)
                # Don't raise - let the dialer handle the error

        # Start listener upgrade in background - responder path will wait for dialer
        # Use transport's nursery or listener's nursery as fallback
        nursery_to_use: trio.Nursery | None = None

        # Prefer transport's nursery (most reliable)
        if self._nursery is not None:
            nursery_to_use = self._nursery
            logger.debug("Using transport's nursery for listener upgrade task")
        else:
            # Fallback to listener's nursery if available
            listener = getattr(self, "_listener", None)
            if listener and hasattr(listener, "_nursery") and listener._nursery:
                nursery_to_use = listener._nursery
                logger.debug("Using listener's nursery for listener upgrade task")

        if nursery_to_use is not None:
            nursery_to_use.start_soon(listener_upgrade_task)
            logger.debug("Started listener upgrade task in background")
        else:
            logger.warning(
                "No nursery for listener upgrade; running synchronously (e.g. tests)"
            )
            await listener_upgrade_task()

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
                bridge = get_webrtc_bridge()
                async with bridge:
                    await bridge.close_peer_connection(pc)
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

        if self.host is None:
            raise WebRTCError("Host must be set for Circuit Relay v2 fallback")

        # Try to reuse existing WebRTCTransport from TransportManager if available
        relay_transport: WebRTCTransport | None = None

        # Get the existing transport manager from the network (not create a new one!)
        # The transport_manager is stored on the network as an attribute
        transport_manager = getattr(self.host.get_network(), "transport_manager", None)
        if transport_manager:
            # get_transport returns the instance (ITransport), not a class
            existing_webrtc_transport = transport_manager.get_transport("webrtc")
            if existing_webrtc_transport is not None:
                # Check if it's a WebRTCTransport instance
                if isinstance(existing_webrtc_transport, WebRTCTransport):
                    relay_transport = existing_webrtc_transport
                    logger.debug(
                        "Reusing existing WebRTC instance from TransportManager"
                    )
                    # Check if transport is started, if not start it
                    if not relay_transport._started:
                        logger.debug("Starting existing WebRTCTransport instance")
                        await relay_transport.start()

        # If no existing instance found, create a new one
        if relay_transport is None:
            logger.debug("Creating new WebRTCTransport instance for fallback")
            relay_transport = WebRTCTransport({})
            relay_transport.set_host(self.host)

        try:
            # Start the relay transport if not already started
            if not relay_transport._started:
                await relay_transport.start()

            # Try to find a relay address for the peer
            peerstore = self.host.get_peerstore() if self.host else None
            relay_addrs_found = False

            if peerstore:
                # Look for existing relay addresses in peerstore
                relay_addrs = peerstore.addrs(peer_id)
                for relay_addr in relay_addrs:
                    if "/p2p-circuit" in str(relay_addr):
                        # Found a relay address, construct WebRTC multiaddr
                        relay_maddr_str = str(relay_addr)
                        # Ensure it ends with /webrtc/p2p/{peer_id}
                        if not relay_maddr_str.endswith(
                            f"/webrtc/p2p/{peer_id.to_base58()}"
                        ):
                            # Construct proper WebRTC multiaddr via relay
                            relay_maddr = Multiaddr(
                                f"{relay_maddr_str}/webrtc/p2p/{peer_id.to_base58()}"
                            )
                        else:
                            relay_maddr = Multiaddr(relay_maddr_str)
                        logger.debug(f"Using existing relay address: {relay_maddr}")
                        relay_addrs_found = True
                        return await relay_transport.dial(relay_maddr)

            # If no relay address in peerstore, use RelayDiscovery
            if not relay_addrs_found and relay_transport._relay_discovery:
                logger.debug("No relay addresses in peerstore, using RelayDiscovery")
                discovered_relays = relay_transport._relay_discovery.get_relays()
                if discovered_relays:
                    # Try to discover relays if none found
                    if not discovered_relays:
                        logger.debug(
                            "No relays discovered yet, triggering discovery..."
                        )
                        await relay_transport._relay_discovery.discover_relays()
                        await trio.sleep(1.0)  # Give discovery time to complete
                        discovered_relays = (
                            relay_transport._relay_discovery.get_relays()
                        )

                    # Try each discovered relay
                    for relay_peer_id in discovered_relays:
                        relay_addrs = (
                            peerstore.addrs(relay_peer_id) if peerstore else []
                        )
                        if relay_addrs:
                            # Use first relay address
                            relay_base_addr = relay_addrs[0]
                            # Construct WebRTC multiaddr via relay
                            relay_maddr = Multiaddr(
                                f"{relay_base_addr}/p2p-circuit/webrtc/p2p/{peer_id.to_base58()}"
                            )
                            logger.debug(f"Using discovered relay: {relay_maddr}")
                            try:
                                return await relay_transport.dial(relay_maddr)
                            except Exception as dial_exc:
                                logger.debug(
                                    f"Failed to dial via relay "
                                    f"{relay_peer_id}: {dial_exc}"
                                )
                                continue  # Try next relay

            # If no relay address found, we can't proceed with fallback
            raise OpenConnectionError(
                f"No relay addr available for {peer_id} for relay fallback"
            )

        finally:
            # Only stop if we created a new instance (not if we reused existing one)
            # Check if this transport is registered in transport_manager
            transport_manager = getattr(
                self.host.get_network(), "transport_manager", None
            )
            is_registered = (
                transport_manager is not None
                and transport_manager.get_transport("webrtc") is relay_transport
            )

            if not is_registered:
                # We created a new instance, so clean it up
                try:
                    await relay_transport.stop()
                except Exception:
                    pass
            else:
                logger.debug(
                    "Skipping stop() for registered WebRTCTransport instance "
                    "(will be managed by transport lifecycle)"
                )

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

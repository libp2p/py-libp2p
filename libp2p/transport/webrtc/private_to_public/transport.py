import logging
from typing import TYPE_CHECKING, Any, cast

from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import Multiaddr
import trio
from trio_asyncio import aio_as_trio, open_loop

from libp2p.abc import IHost, IListener, IRawConnection, ISecureConn, ITransport
from libp2p.custom_types import THandler
from libp2p.peer.id import ID
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
    generate_ufrag,
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
        self._renewal_task = None
        self.supported_protocols: set[str] = {"webrtc-direct", "p2p"}
        self.signal_service: SignalService | None = None
        logger.info("WebRTC-Direct Transport initialized")

    async def start(self, nursery: trio.Nursery) -> None:
        """Start the WebRTC-Direct transport."""
        if self._started:
            return

        if not self.host:
            raise WebRTCError("Host must be set before starting transport")

        # Generate certificate for this transport
        self.cert_mgr = WebRTCCertificate()

        # TODO: Start certificate renewal loop properly with cancellation support
        # For now, skip renewal to avoid hanging tests
        # self._renewal_task = nursery.start_soon(self.cert_mgr.renewal_loop)
        self._renewal_task = None

        if self.signal_service is None:
            self.signal_service = SignalService(self.host)
        network = self.host.get_network()
        try:
            await self.signal_service.listen(network, None)
        except Exception:
            logger.warning("Failed to start WebRTC signaling service", exc_info=True)

        self._started = True
        logger.info("WebRTC-Direct Transport started")

    async def stop(self) -> None:
        """Stop the WebRTC-Direct transport."""
        if not self._started:
            return

        # Clean up connections
        for conn_id in list(self.active_connections.keys()):
            await self._cleanup_connection(conn_id)

        # Cancel the renewal task if it's running
        # (Not implemented yet - renewal loop is disabled)
        if self._renewal_task is not None:
            # TODO: Implement proper task cancellation
            self._renewal_task = None

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

            if self.cert_mgr is None:
                raise WebRTCError(
                    "Certificate manager not initialised for WebRTC-Direct"
                )
            if self.host is None:
                raise WebRTCError("Transport host must be set before dialing")

            punch_metadata = {
                "ufrag": ufrag,
                "peer_id": str(self.host.get_id()),
                "certhash": self.cert_mgr.certhash,
                "fingerprint": self.cert_mgr.fingerprint,
                "role": "client",
            }

            print(f"UDP punch toward {ip}:{port} with metadata {punch_metadata}")
            try:
                await self.udp_puncher.punch_hole(ip, port, punch_metadata)
            except Exception as punch_exc:
                logger.warning(
                    "UDP hole punching failed prior to dialing: %s", punch_exc
                )
            else:
                # Give the remote listener a brief moment to register the punch metadata
                await trio.sleep(0.2)

            async with open_loop():
                conn_id = str(peer_id)
                rtc_config = RTCConfiguration(iceServers=[])
                direct_peer_connection = (
                    await DirectPeerConnection.create_dialer_rtc_peer_connection(
                        role="client", ufrag=ufrag, rtc_configuration=rtc_config
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
                        peer_connection=direct_peer_connection,
                        remote_addr=maddr,
                        remote_peer_id=peer_id,
                        signal_service=None,
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

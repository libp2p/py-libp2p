from collections.abc import Awaitable
from dataclasses import dataclass
import json
import logging
import socket
from typing import TYPE_CHECKING, Any, cast

from aioice.candidate import Candidate
from aiortc import RTCConfiguration, RTCIceCandidate, RTCSessionDescription
from aiortc.rtcicetransport import candidate_from_aioice
from multiaddr import Multiaddr
import trio
import trio.socket
from trio_asyncio import open_loop

from libp2p.abc import IHost, IListener
from libp2p.peer.id import ID
from libp2p.transport.webrtc.async_bridge import get_webrtc_bridge

from ..constants import WebRTCError
from .connect import connect
from .direct_rtc_connection import DirectPeerConnection
from .gen_certificate import WebRTCCertificate
from .util import (
    canonicalize_certhash,
    extract_from_multiaddr,
    fingerprint_to_certhash,
)

if TYPE_CHECKING:
    from libp2p.network.swarm import Swarm
    from libp2p.transport.webrtc.signal_service import SignalService

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


@dataclass
class UDPMuxServer:
    socket: trio.socket.SocketType
    is_ipv4: bool
    is_ipv6: bool
    port: int
    owner: "WebRTCDirectListener"
    peer_id: ID
    cancel_scope: trio.CancelScope | None = None


@dataclass
class PendingSession:
    ufrag: str
    peer_connection: DirectPeerConnection | None = None
    remote_host: str | None = None
    remote_port: int | None = None
    remote_peer_id: ID | None = None
    certhash: str | None = None
    remote_info: dict[str, Any] | None = None
    client_multiaddr: Multiaddr | None = None
    offer: RTCSessionDescription | None = None
    ice_listener_registered: bool = False
    finalized: bool = False
    finalizing: bool = False


UDP_MUX_LISTENERS: list[UDPMuxServer] = []
UDP_BUFFER_SIZE = 2048
PUNCH_MESSAGE_TYPE = "punch"


class WebRTCDirectListener(IListener):
    """
    Private-to-public WebRTC-Direct transport listener implementation.
    """

    def __init__(
        self,
        transport: Any,
        cert: WebRTCCertificate,
        rtc_configuration: RTCConfiguration,
        signal_service: "SignalService | None",
    ) -> None:
        self.transport = transport
        self._is_listening = False
        self._listen_addrs: list[Multiaddr] = []
        self.cert: WebRTCCertificate = cert
        self.rtc_configuration = rtc_configuration
        self._nursery: trio.Nursery | None = None
        self._udp_servers: list[UDPMuxServer] = []
        self.sessions: dict[str, PendingSession] = {}
        self.signal_service = signal_service
        self._ice_handler_registered = False
        self._connection_state_handler_registered = False
        self.host: IHost | None = getattr(transport, "host", None)

        if self.signal_service is not None:
            self.signal_service.set_handler("offer", self._handle_signal_offer)
            self.signal_service.add_handler("ice", self._handle_signal_ice)
            self.signal_service.add_handler(
                "connection_state", self._handle_signal_connection_state
            )
            self._ice_handler_registered = True
            self._connection_state_handler_registered = True

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Return the advertised listening addresses for this listener.
        """
        return tuple(self._listen_addrs)

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening for incoming connections on the given multiaddr.
        """
        if self._is_listening:
            return True

        self._nursery = nursery

        try:
            opts = extract_from_multiaddr(maddr)
            host = opts[0] or "0.0.0.0"
            port = opts[1] if opts[1] is not None else 0
            family = opts[2] if opts[2] is not None else 4

            udp_mux_server = None
            if port != 0:
                for server in UDP_MUX_LISTENERS:
                    if server.port == port:
                        udp_mux_server = server
                        break

                if udp_mux_server is not None:
                    if (udp_mux_server.is_ipv4 and family == 4) or (
                        udp_mux_server.is_ipv6 and family == 6
                    ):
                        raise Exception(
                            f"UDP mux server already bound to {host}:{port}"
                        )
                    if udp_mux_server.peer_id != self.transport.host.get_id():
                        raise Exception(
                            f"Another peer is performing UDP mux on {host}:{port}"
                        )

            if udp_mux_server is None:
                logger.info("Starting UDP mux server on %s:%s", host, port)
                udp_mux_server = await self.start_udp_mux_server(
                    host, int(port), int(family), nursery
                )
                UDP_MUX_LISTENERS.append(udp_mux_server)
                self._udp_servers.append(udp_mux_server)
            elif udp_mux_server not in self._udp_servers:
                self._udp_servers.append(udp_mux_server)

            actual_port = udp_mux_server.port
            advertise_host = host
            if advertise_host in ("0.0.0.0", "::"):
                try:
                    advertise_host = socket.gethostbyname(socket.gethostname())
                except Exception:
                    advertise_host = "127.0.0.1" if family == 4 else "::1"

            certhash = self.cert.certhash
            peer_id = self.transport.host.get_id()
            proto = "ip6" if ":" in advertise_host else "ip4"
            listen_multiaddr = Multiaddr(
                f"/{proto}/{advertise_host}/udp/{actual_port}"
                f"/webrtc-direct/certhash/{certhash}/p2p/{peer_id}"
            )

            self._listen_addrs.append(listen_multiaddr)
            self._is_listening = True
            logger.info(
                "WebRTC-Direct listener started with multiaddr: %s", listen_multiaddr
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start WebRTC-Direct listener: {e}")
            return False

    async def start_udp_mux_server(
        self, host: str, port: int, family: int, nursery: trio.Nursery
    ) -> UDPMuxServer:
        """
        Start a UDP mux server for the given host/port/family.
        """
        if family not in [4, 6]:
            raise Exception("Should be IPv4 or IPv6 family")
        addr_family = socket.AF_INET if family == 4 else socket.AF_INET6
        bind_host = host or ("0.0.0.0" if family == 4 else "::")

        udp_socket = trio.socket.socket(addr_family, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_result = udp_socket.bind((bind_host, port))
        if isinstance(bind_result, Awaitable):
            await bind_result
        actual_port = udp_socket.getsockname()[1]

        cancel_scope = trio.CancelScope()
        mux_server = UDPMuxServer(
            socket=udp_socket,
            is_ipv4=(family == 4),
            is_ipv6=(family == 6),
            port=actual_port,
            owner=self,
            peer_id=self.transport.host.get_id(),
            cancel_scope=cancel_scope,
        )

        async def _serve() -> None:
            with cancel_scope:
                await self._serve_udp_mux(mux_server)

        nursery.start_soon(_serve)
        return mux_server

    async def _serve_udp_mux(self, mux_server: UDPMuxServer) -> None:
        sock = mux_server.socket
        while True:
            try:
                data, addr = await sock.recvfrom(UDP_BUFFER_SIZE)
            except trio.Cancelled:
                break
            except trio.BrokenResourceError:
                break
            except OSError as exc:
                logger.debug("UDP mux server socket error: %s", exc)
                break

            if not data:
                continue

            remote_host, remote_port = addr[0], addr[1]
            await self._dispatch_udp_packet(mux_server, data, remote_host, remote_port)

        try:
            sock.close()
        except Exception:
            pass

    async def _dispatch_udp_packet(
        self,
        mux_server: UDPMuxServer,
        data: bytes,
        remote_host: str,
        remote_port: int,
    ) -> None:
        if not self._is_listening:
            return

        if self._nursery:
            try:
                self._nursery.start_soon(
                    self._handle_udp_packet,
                    mux_server,
                    data,
                    remote_host,
                    remote_port,
                )
            except Exception as exc:
                logger.debug("Failed to schedule UDP packet handler: %s", exc)
        else:
            await self._handle_udp_packet(mux_server, data, remote_host, remote_port)

    async def _handle_udp_packet(
        self,
        mux_server: UDPMuxServer,
        data: bytes,
        remote_host: str,
        remote_port: int,
    ) -> None:
        try:
            message = json.loads(data.decode("utf-8"))
        except Exception:
            logger.debug(
                "Ignored non-JSON UDP packet from %s:%s", remote_host, remote_port
            )
            return

        if message.get("type") != PUNCH_MESSAGE_TYPE:
            return

        ufrag = message.get("ufrag")
        if not ufrag:
            logger.debug(
                "Punch packet missing ufrag from %s:%s", remote_host, remote_port
            )
            return

        session = self.sessions.get(ufrag)
        if session is None:
            session = PendingSession(ufrag=ufrag)
            self.sessions[ufrag] = session

        session.remote_info = {
            "peer_id": message.get("peer_id"),
            "certhash": message.get("certhash"),
            "fingerprint": message.get("fingerprint"),
        }
        session.remote_host = remote_host
        session.remote_port = remote_port

        await self.incoming_connection(ufrag)

    async def incoming_connection(
        self,
        ufrag: str,
    ) -> None:
        """
        Handle an incoming connection for the given ICE ufrag, remote host, and port.
        """
        session = self.sessions.get(ufrag)
        if session is None:
            session = PendingSession(ufrag=ufrag)
            self.sessions[ufrag] = session

        if session.peer_connection is None:
            logger.info("Create peer connection for session %s", ufrag)
            session.peer_connection = (
                await DirectPeerConnection.create_dialer_rtc_peer_connection(
                    role="server",
                    ufrag=ufrag,
                    rtc_configuration=self.rtc_configuration,
                    certificate=self.cert,
                )
            )
            if (
                self.signal_service is not None
                and session.peer_connection is not None
                and not session.ice_listener_registered
            ):

                def _queue_local_candidate(
                    candidate: RTCIceCandidate | None,
                ) -> None:
                    if self.signal_service is None or session.remote_peer_id is None:
                        return
                    if candidate is None:
                        self.signal_service.enqueue_local_candidate(
                            session.remote_peer_id,
                            None,
                            extra={"ufrag": session.ufrag},
                        )
                        return
                    candidate_any = cast(Any, candidate)
                    if hasattr(candidate_any, "to_sdp"):
                        candidate_sdp = candidate_any.to_sdp()
                    else:
                        candidate_sdp = getattr(candidate_any, "candidate", None)
                    self.signal_service.enqueue_local_candidate(
                        session.remote_peer_id,
                        {
                            "candidate": candidate_sdp,
                            "sdpMid": candidate_any.sdpMid,
                            "sdpMLineIndex": candidate_any.sdpMLineIndex,
                        },
                        extra={"ufrag": session.ufrag},
                    )

                session.peer_connection.peer_connection.on(
                    "icecandidate", _queue_local_candidate
                )
                session.ice_listener_registered = True

        if session.remote_info is None:
            logger.debug("Session %s missing remote info; waiting", ufrag)
            return

        peer_id_str = session.remote_info.get("peer_id")
        certhash = session.remote_info.get("certhash")

        if not peer_id_str or not certhash:
            logger.debug("Session %s missing peer metadata; waiting", ufrag)
            return

        try:
            session.remote_peer_id = ID.from_base58(str(peer_id_str))
        except Exception as exc:
            logger.warning("Invalid peer ID in punch for session %s: %s", ufrag, exc)
            return

        session.certhash = certhash

        if (
            session.remote_host is not None
            and session.remote_port is not None
            and session.remote_peer_id is not None
        ):
            ip_proto = "ip6" if ":" in session.remote_host else "ip4"
            session.client_multiaddr = Multiaddr(
                f"/{ip_proto}/{session.remote_host}/udp/{session.remote_port}"
                f"/webrtc-direct/certhash/{certhash}/p2p/{session.remote_peer_id}"
            )

        if session.offer is not None and session.client_multiaddr is not None:
            await self._finalize_session(session)

    async def _handle_signal_offer(
        self, message: dict[str, Any], sender_peer_id: str
    ) -> None:
        ufrag = message.get("ufrag")
        if not ufrag:
            logger.debug("Received signaling offer without ufrag; ignoring")
            return

        try:
            sender_id = ID.from_base58(sender_peer_id)
        except Exception:
            logger.debug("Invalid sender peer ID %s in signaling offer", sender_peer_id)
            return

        session = self.sessions.get(ufrag)
        if session is None:
            session = PendingSession(ufrag=ufrag)
            self.sessions[ufrag] = session
        if session.finalized or session.finalizing:
            return

        session.offer = RTCSessionDescription(
            sdp=message.get("sdp", ""),
            type=message.get("sdpType", "offer"),
        )
        session.certhash = message.get("certhash", session.certhash)
        if session.remote_peer_id is None:
            session.remote_peer_id = sender_id

        if (
            session.peer_connection is not None
            and session.remote_host is not None
            and session.remote_port is not None
        ):
            ip_proto = "ip6" if ":" in session.remote_host else "ip4"
            session.client_multiaddr = Multiaddr(
                f"/{ip_proto}/{session.remote_host}/udp/{session.remote_port}"
                f"/webrtc-direct/certhash/{session.certhash}/p2p/{session.remote_peer_id}"
            )
            await self._finalize_session(session)

    async def _handle_signal_ice(
        self, message: dict[str, Any], sender_peer_id: str
    ) -> None:
        ufrag = message.get("ufrag")
        if not ufrag:
            return
        session = self.sessions.get(ufrag)
        if session is None or session.peer_connection is None:
            return
        if (
            session.remote_peer_id is not None
            and session.remote_peer_id.to_base58() != sender_peer_id
        ):
            return

        candidate_payload = message.get("candidate")
        bridge = get_webrtc_bridge()
        peer_conn = session.peer_connection.peer_connection
        async with bridge:
            if candidate_payload is None:
                await bridge.add_ice_candidate(peer_conn, None)
                return
            try:
                candidate_obj = candidate_from_aioice(
                    Candidate.from_sdp(candidate_payload.get("candidate", ""))
                )
                candidate_obj.sdpMid = candidate_payload.get("sdpMid")
                candidate_obj.sdpMLineIndex = candidate_payload.get("sdpMLineIndex")
                await bridge.add_ice_candidate(peer_conn, candidate_obj)
            except Exception:
                logger.debug(
                    "Failed to add ICE candidate from %s", sender_peer_id, exc_info=True
                )

    async def _handle_signal_connection_state(
        self, message: dict[str, Any], sender_peer_id: str
    ) -> None:
        if message.get("state") != "failed":
            return
        logger.warning(
            "Remote peer %s reported WebRTC connection failure: %s",
            sender_peer_id,
            message.get("reason"),
        )

    async def _finalize_session(self, session: PendingSession) -> None:
        if session.finalized or session.finalizing:
            return

        if (
            session.peer_connection is None
            or session.offer is None
            or session.client_multiaddr is None
            or session.remote_peer_id is None
        ):
            return

        signal_service = self.transport.signal_service
        if signal_service is None:
            raise WebRTCError("Signal service not available for WebRTC-Direct listener")

        session.finalizing = True

        async def send_answer(
            answer_desc: RTCSessionDescription, handler_ufrag: str
        ) -> None:
            await signal_service.send_answer(
                session.remote_peer_id,
                answer_desc.sdp,
                answer_desc.type,
                session.certhash or "",
                extra={"ufrag": handler_ufrag},
            )

        try:
            swarm = cast("Swarm", self.host.get_network()) if self.host else None
            security_multistream = (
                swarm.upgrader.security_multistream if swarm is not None else None
            )
            async with open_loop():
                connection, _ = await connect(
                    session.peer_connection,
                    session.ufrag,
                    role="server",
                    remote_addr=session.client_multiaddr,
                    remote_peer_id=session.remote_peer_id,
                    incoming_offer=session.offer,
                    certhash=session.certhash,
                    answer_handler=send_answer,
                    security_multistream=security_multistream,
                )

            connection_any = cast(Any, connection)

            actual_certhash = None
            remote_fingerprint = getattr(connection_any, "remote_fingerprint", None)
            if remote_fingerprint:
                try:
                    actual_certhash = fingerprint_to_certhash(remote_fingerprint)
                except Exception:
                    actual_certhash = None
            elif hasattr(session.peer_connection, "remoteFingerprint"):
                try:
                    fp_obj = session.peer_connection.remoteFingerprint()
                except Exception:
                    fp_obj = None
                if fp_obj and fp_obj.value:
                    remote_fingerprint = f"{fp_obj.algorithm} {fp_obj.value.upper()}"
                    setattr(connection_any, "remote_fingerprint", remote_fingerprint)
                    try:
                        actual_certhash = fingerprint_to_certhash(remote_fingerprint)
                    except Exception:
                        actual_certhash = None

            expected_certhash = session.certhash
            if expected_certhash and actual_certhash:
                if expected_certhash != actual_certhash:
                    logger.warning(
                        "Rejecting WebRTC-Direct conn due to certhash mismatch",
                        session.ufrag,
                    )
                    await connection.close()
                    return

            if actual_certhash is None:
                actual_certhash = expected_certhash

            canonical_remote = (
                canonicalize_certhash(session.client_multiaddr, actual_certhash)
                if actual_certhash
                else session.client_multiaddr
            )
            setattr(connection_any, "remote_multiaddr", canonical_remote)

            if self._listen_addrs:
                setattr(connection_any, "local_multiaddr", self._listen_addrs[0])

            if getattr(connection_any, "local_fingerprint", None) is None:
                setattr(connection_any, "local_fingerprint", self.cert.fingerprint)

            fingerprint_hint = (
                session.remote_info.get("fingerprint") if session.remote_info else None
            )
            if (
                fingerprint_hint
                and getattr(connection_any, "remote_fingerprint", None) is None
            ):
                setattr(connection_any, "remote_fingerprint", fingerprint_hint)

            if getattr(connection_any, "remote_peer_id", None) is None:
                setattr(connection_any, "remote_peer_id", session.remote_peer_id)

            if (
                self.transport.host is not None
                and canonical_remote is not None
                and session.remote_peer_id is not None
            ):
                try:
                    self.transport.host.get_peerstore().add_addrs(
                        session.remote_peer_id,
                        [canonical_remote],
                        3600,
                    )
                except Exception:
                    logger.debug(
                        "Failed to cache remote WebRTC-Direct address for %s",
                        session.remote_peer_id,
                    )

            await self.transport.register_incoming_connection(connection)
            logger.info(
                "WebRTC-Direct incoming connection established with %s",
                session.remote_peer_id,
            )
            await signal_service.flush_local_ice(session.remote_peer_id)
            await signal_service.flush_ice_candidates(session.remote_peer_id)
            session.finalized = True
        except Exception as exc:
            session.finalized = False
            session.finalizing = False
            logger.exception("Failed to finalize WebRTC-Direct session %s", exc)
            if "connection" in locals():
                await connection.close()
            return
        finally:
            session.finalizing = False
            if session.finalized:
                self.sessions.pop(session.ufrag, None)

    async def close(self) -> None:
        self._is_listening = False
        self._nursery = None

        for server in list(self._udp_servers):
            if server.cancel_scope is not None:
                server.cancel_scope.cancel()
            try:
                server.socket.close()
            except Exception:
                pass
            try:
                UDP_MUX_LISTENERS.remove(server)
            except ValueError:
                pass
        self._udp_servers.clear()
        self.sessions.clear()

        if self.signal_service is not None:
            self.signal_service.set_handler("offer", None)
            if self._ice_handler_registered:
                self.signal_service.remove_handler("ice", self._handle_signal_ice)
            if self._connection_state_handler_registered:
                self.signal_service.remove_handler(
                    "connection_state", self._handle_signal_connection_state
                )

        logger.info("WebRTC-Direct listener closed")

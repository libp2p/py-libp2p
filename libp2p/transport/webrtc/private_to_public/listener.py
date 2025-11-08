from collections.abc import Awaitable
from dataclasses import dataclass
import json
import logging
import socket
from typing import Any

from aiortc import RTCConfiguration
from multiaddr import Multiaddr
import trio
import trio.socket

from libp2p.abc import IListener
from libp2p.peer.id import ID

from .connect import connect
from .direct_rtc_connection import DirectPeerConnection
from .gen_certificate import WebRTCCertificate
from .util import extract_from_multiaddr

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
    ) -> None:
        self.transport = transport
        # self.handler = handler
        self._is_listening = False
        self._listen_addrs: list[Multiaddr] = []
        self.cert: WebRTCCertificate = cert
        self.peer_connections: dict[str, DirectPeerConnection] = {}
        self.rtc_configuration = rtc_configuration
        self._nursery: trio.Nursery | None = None
        self._udp_servers: list[UDPMuxServer] = []

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
                udp_mux_server = self.start_udp_mux_server(
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

    def start_udp_mux_server(
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
            raise RuntimeError("trio.socket.bind returned unexpected awaitable")
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

        remote_info = {
            "peer_id": message.get("peer_id"),
            "certhash": message.get("certhash"),
            "fingerprint": message.get("fingerprint"),
        }

        await self.incoming_connection(ufrag, remote_host, remote_port, remote_info)

    async def incoming_connection(
        self,
        ufrag: str,
        remote_host: str,
        remote_port: int,
        remote_info: dict[str, Any] | None = None,
    ) -> None:
        """
        Handle an incoming connection for the given ICE ufrag, remote host, and port.
        """
        key = f"{remote_host}:{remote_port}:{ufrag}"
        peer_connection = self.peer_connections.get(key)

        if peer_connection is not None:
            logger.debug(f"Already got peer connection for {key}")
            return

        logger.info(f"Create peer connection for {key}")

        peer_connection = await DirectPeerConnection.create_dialer_rtc_peer_connection(
            role="server",
            ufrag=ufrag,
            rtc_configuration=self.rtc_configuration,
            certificate=self.cert,
        )

        self.peer_connections[key] = peer_connection

        try:
            if remote_info is None:
                remote_info = {}

            peer_id_str = remote_info.get("peer_id")
            certhash = remote_info.get("certhash")

            if not peer_id_str or not certhash:
                logger.debug(
                    "Missing peer metadata in punch from %s:%s",
                    remote_host,
                    remote_port,
                )
                self.peer_connections.pop(key, None)
                try:
                    await peer_connection.close()
                except Exception:
                    pass
                return

            try:
                remote_peer_id = ID.from_base58(str(peer_id_str))
            except Exception as exc:
                logger.warning(
                    "Invalid peer ID in punch from %s:%s: %s",
                    remote_host,
                    remote_port,
                    exc,
                )
                self.peer_connections.pop(key, None)
                try:
                    await peer_connection.close()
                except Exception:
                    pass
                return

            ip_proto = "ip6" if ":" in remote_host else "ip4"
            client_multiaddr = Multiaddr(
                f"/{ip_proto}/{remote_host}/udp/{remote_port}"
                f"/webrtc-direct/certhash/{certhash}/p2p/{remote_peer_id}"
            )

            connection = await connect(
                peer_connection,
                ufrag,
                role="server",
                remote_addr=client_multiaddr,
                remote_peer_id=remote_peer_id,
            )

            if connection is None:
                logger.warning("WebRTC-Direct server connect returned no connection")
                self.peer_connections.pop(key, None)
                try:
                    await peer_connection.close()
                except Exception:
                    pass
                return

            fingerprint_hint = remote_info.get("fingerprint") if remote_info else None
            if (
                fingerprint_hint
                and getattr(connection, "remote_fingerprint", None) is None
            ):
                setattr(connection, "remote_fingerprint", fingerprint_hint)

            if getattr(connection, "remote_peer_id", None) is None:
                setattr(connection, "remote_peer_id", remote_peer_id)

            self.peer_connections.pop(key, None)

            await self.transport.register_incoming_connection(connection)
            logger.info(
                "WebRTC-Direct incoming connection established with %s", remote_peer_id
            )
        except Exception as err:
            logger.error(
                "Failed to establish incoming WebRTC-Direct connection from %s:%s: %s",
                remote_host,
                remote_port,
                err,
            )
            self.peer_connections.pop(key, None)
            try:
                await peer_connection.close()
            except Exception:
                pass

    async def close(self) -> None:
        """Close the listener."""
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

        logger.info("WebRTC-Direct listener closed")

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Get listener addresses."""
        return tuple(self._listen_addrs)

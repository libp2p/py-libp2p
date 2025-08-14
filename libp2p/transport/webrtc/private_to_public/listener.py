from libp2p.abc import IHost, IListener
import logging
from libp2p.custom_types import THandler
from typing import Any
from .gen_certificate import WebRTCCertificate
from multiaddr import Multiaddr
import trio
from dataclasses import dataclass
from libp2p.peer.id import ID
from .util import extract_from_multiaddr
from .direct_rtc_connection import DirectPeerConnection
from aiortc import RTCConfiguration
from .connect import connect

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")

@dataclass
class UDPMuxServer:
    server: any  
    is_ipv4: bool
    is_ipv6: bool
    port: int
    owner: "WebRTCDirectListener"
    peer_id: ID


UDP_MUX_LISTENERS: list[UDPMuxServer] = []

class WebRTCDirectListener(IListener):
    """
    Private-to-public WebRTC-Direct transport listener implementation.
    """

    
    def __init__(self, transport: Any, cert: WebRTCCertificate, rtc_configuration:RTCConfiguration) -> None:
        self.transport = transport
        # self.handler = handler
        self._is_listening = False
        self._listen_addrs: list[Multiaddr] = []
        self.cert: WebRTCCertificate = cert
        self.peer_connections: dict[str, DirectPeerConnection] = {}
        self.rtc_configuration = rtc_configuration

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening for incoming connections on the given multiaddr.
        """
        if self._is_listening:
            return True

        try:
            opts = extract_from_multiaddr(maddr)
            host = opts.get("host")
            port = opts.get("port", 0)
            family = opts.get("family", 4)

            udp_mux_server = None
            if port is not 0: 
                for s in self.UDP_MUX_LISTENERS:
                    if s.port == port:
                        udp_mux_server = s
                        break

                # Make sure the port is free for the given family
                if udp_mux_server is not None and (
                    (udp_mux_server.is_ipv4 and family == 4) or (udp_mux_server.is_ipv6 and family == 6)
                ):
                    raise Exception(f"There is already a listener for {host}:{port}")

                # Check that we own the mux server
                if udp_mux_server is not None and udp_mux_server.peer_id != self.transport.host.get_id():
                    raise Exception(f"Another peer is already performing UDP mux on {host}:{port}")

            # Start the mux server if we don't have one already
            if udp_mux_server is None:
                logger.info(f"Starting UDP mux server on {host}:{port}")
                udp_mux_server = self.start_udp_mux_server(host, port, family, nursery)
                UDP_MUX_LISTENERS.append(udp_mux_server)

            # Set family flags
            if family == 4:
                udp_mux_server.is_ipv4 = True
            elif family == 6:
                udp_mux_server.is_ipv6 = True

            # Save server and listen address
            self.stun_server = udp_mux_server.server
            self._listen_addrs.append(maddr)
            self._is_listening = True
            logger.info("WebRTC-Direct listener started")
            return True

        except Exception as e:
            logger.error(f"Failed to start WebRTC-Direct listener: {e}")
            return False

    def start_udp_mux_server(self, host: str, port: int, family: int, nursery: trio.Nursery) -> UDPMuxServer:
        """
        Start a UDP mux server for the given host/port/family.
        """
        
        if family not in [4, 6]:
            raise Exception("Should be IPv4 or IPv6 family")
        # with trio.open_nursery() as nursery:
        #     nursery.start_soon(self.incoming_connection)
        
        return UDPMuxServer(
            server=server,
            is_ipv4=(family == 4),
            is_ipv6=(family == 6),
            port=port,
            owner=self,
            peer_id=self.transport.host.get_id(),
        )
        
    async def incoming_connection(self, ufrag: str, remote_host: str, remote_port: int) -> None:
        """
        Handle an incoming connection for the given ICE ufrag, remote host, and port.
        """
        key = f"{remote_host}:{remote_port}:{ufrag}"
        peer_connection = self.connections.get(key)

        if peer_connection is not None:
            logger.debug(f"Already got peer connection for {key}")
            return

        logger.info(f"Create peer connection for {key}")

        peer_connection = await DirectPeerConnection.create_dialer_rtc_peer_connection(
            role="server",
            ufrag=ufrag,
            rtc_configuration=self.rtc_configuration,
            certificate=self.cert
        )

        self.connections[key] = peer_connection

        try:
            await connect(
                peer_connection,
                ufrag,
                role="server"
            )
        except Exception as err:
            await peer_connection.close()
            raise err
    
    

    async def close(self) -> None:
        """Close the listener."""
        self._is_listening = False
        logger.info("WebRTC-Direct listener closed")

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Get listener addresses."""
        return tuple(self._listen_addrs)
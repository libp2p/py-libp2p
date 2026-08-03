import logging
import socket
from typing import TYPE_CHECKING

from zeroconf import (
    EventLoopBlocked,
    ServiceInfo,
    Zeroconf,
)

if TYPE_CHECKING:
    from libp2p.abc import IHost

logger = logging.getLogger(__name__)

MDNS_DOMAIN = "local"


class PeerBroadcaster:
    """
    Broadcasts this peer's presence on the local network using mDNS/zeroconf.

    Registers a service with the peer's multiaddresses in the TXT record
    as per libp2p spec (dnsaddr format).
    """

    def __init__(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        service_name: str,
        peer_id: str,
        port: int,
        listen_addrs: list[str] | None = None,
        host: "IHost | None" = None,
    ):
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.peer_id = peer_id
        self.port = port
        self.service_name = service_name
        self.host = host
        self.listen_addrs = listen_addrs

        # Derive peer_name from service_name
        # (e.g., "abc123._p2p._udp.local." -> "abc123")
        # Spec: "host-name is derived from the peer's name and p2p.local"
        self.peer_name = service_name.split(".")[0]

        # Build service_info with placeholder addresses
        # Actual addresses are resolved during register() when host is ready
        self._build_service_info()

    def _build_service_info(self, resolved_addrs: list[str] | None = None) -> None:
        """Build ServiceInfo with resolved addresses."""
        local_ips = self._get_local_ips()

        # Use resolved_addrs if provided, otherwise use stored listen_addrs
        addrs_to_use = (
            resolved_addrs if resolved_addrs is not None else self.listen_addrs
        )

        # Build dnsaddr TXT records per spec
        properties = self._build_txt_properties(
            addrs_to_use, local_ips, self.port, self.peer_id
        )

        self.service_info = ServiceInfo(
            type_=self.service_type,
            name=self.service_name,
            port=self.port,
            properties=properties,
            # Spec: host-name is derived from peer's name and p2p.local
            server=f"{self.peer_name}.{MDNS_DOMAIN}",
            addresses=[self._ip_to_bytes(ip) for ip in local_ips],
        )

    def _resolve_host_addrs(self) -> list[str]:
        """Resolve multiaddr strings from host's transport addresses."""
        if self.host is None:
            return self.listen_addrs or []

        addrs = []
        for addr in self.host.get_transport_addrs():
            addr_str = str(addr)
            # Strip /p2p/QmId suffix if present
            if "/p2p/" in addr_str:
                addr_str = addr_str.rsplit("/p2p/", 1)[0]
            addrs.append(addr_str)
        return addrs

    def _get_local_ips(self) -> list[str]:
        """Get all local IP addresses (both IPv4 and IPv6)"""
        ips = []

        # Get IPv4
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ips.append(s.getsockname()[0])
        except Exception:
            ips.append("127.0.0.1")

        # Get IPv6
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
                s.connect(("2001:4860:4860::8888", 80))
                ipv6 = s.getsockname()[0]
                if ipv6 != "::1":
                    ips.append(ipv6)
        except Exception:
            pass  # IPv6 not available

        return ips

    def _ip_to_bytes(self, ip: str) -> bytes:
        """Convert IP string to bytes for zeroconf"""
        try:
            # Try IPv4
            return socket.inet_aton(ip)
        except OSError:
            # Try IPv6
            return socket.inet_pton(socket.AF_INET6, ip)

    @staticmethod
    def is_suitable_for_mdns(addr_str: str) -> bool:
        """
        Check if a multiaddr string is suitable for mDNS advertisement.

        Filters out circuit relay, browser transports, and non-.local DNS names
        per go-libp2p's isSuitableForMDNS.
        """
        # Not suitable: circuit relay
        if "/p2p-circuit" in addr_str:
            return False

        # Not suitable: browser transports (browsers don't use mDNS)
        browser_protocols = [
            "/quic-v1/webtransport",
            "/webrtc",
            "/webrtc-direct",
            "/ws",
            "/wss",
        ]
        for proto in browser_protocols:
            if proto in addr_str:
                return False

        # Not suitable: non-.local DNS names (require unicast DNS)
        if addr_str.startswith(("/dns4/", "/dns6/", "/dns/", "/dnsaddr/")):
            if ".local" not in addr_str.lower():
                return False

        return True

    def _build_txt_properties(
        self,
        listen_addrs: list[str] | None,
        local_ips: list[str],
        port: int,
        peer_id: str,
    ) -> dict[bytes, bytes]:
        """
        Build TXT record properties per libp2p mDNS spec.

        Spec: TXT record contains multiaddresses as dnsaddr=/.../p2p/QmId.
        """
        properties: dict[bytes, bytes] = {}

        # If listen_addrs provided, use those (filtered)
        # otherwise construct from local IPs
        if listen_addrs:
            # Filter out unsuitable addresses
            multiaddrs = [a for a in listen_addrs if self.is_suitable_for_mdns(a)]
        else:
            multiaddrs = []
            for ip in local_ips:
                if ":" in ip:
                    multiaddrs.append(f"/ip6/{ip}/tcp/{port}/p2p/{peer_id}")
                else:
                    multiaddrs.append(f"/ip4/{ip}/tcp/{port}/p2p/{peer_id}")

        # Ensure each address has /p2p/{peer_id} suffix per spec
        p2p_suffix = f"/p2p/{peer_id}"
        multiaddrs = [
            addr if addr.endswith(p2p_suffix) else f"{addr}{p2p_suffix}"
            for addr in multiaddrs
        ]

        # Add each multiaddr as a dnsaddr TXT record
        for i, addr in enumerate(multiaddrs):
            if i == 0:
                properties[b"dnsaddr"] = addr.encode()
            else:
                properties[f"dnsaddr{i + 1}".encode()] = addr.encode()

        return properties

    def register(self) -> None:
        """Register the peer's mDNS service on the network."""
        try:
            # Resolve addresses from host at registration time (host is ready)
            resolved_addrs = self._resolve_host_addrs()
            if resolved_addrs:
                self._build_service_info(resolved_addrs)

            self.zeroconf.register_service(self.service_info)
            logger.debug(f"mDNS service registered: {self.service_name}")
        except EventLoopBlocked as e:
            logger.warning(
                "EventLoopBlocked while registering mDNS '%s': %s",
                self.service_name,
                e,
            )
        except Exception as e:
            logger.error(
                "Unexpected error during mDNS registration for '%s': %r",
                self.service_name,
                e,
            )

    def unregister(self) -> None:
        """Unregister the peer's mDNS service from the network."""
        try:
            self.zeroconf.unregister_service(self.service_info)
            logger.debug(f"mDNS service unregistered: {self.service_name}")
        except EventLoopBlocked as e:
            logger.warning(
                "EventLoopBlocked while unregistering mDNS '%s': %s",
                self.service_name,
                e,
            )
        except Exception as e:
            logger.error(
                "Unexpected error during mDNS unregistration for '%s': %r",
                self.service_name,
                e,
            )

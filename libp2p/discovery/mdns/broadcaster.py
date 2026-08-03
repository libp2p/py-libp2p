import logging
import socket

from zeroconf import (
    EventLoopBlocked,
    ServiceInfo,
    Zeroconf,
)

logger = logging.getLogger(__name__)


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
    ):
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.peer_id = peer_id
        self.port = port
        self.service_name = service_name

        # Get local IP addresses (both IPv4 and IPv6)
        local_ips = self._get_local_ips()
        hostname = socket.gethostname()

        # Build dnsaddr TXT records per spec
        properties = self._build_txt_properties(listen_addrs, local_ips, port, peer_id)

        self.service_info = ServiceInfo(
            type_=self.service_type,
            name=self.service_name,
            port=self.port,
            properties=properties,
            server=f"{hostname}.local.",
            addresses=[self._ip_to_bytes(ip) for ip in local_ips],
        )

    def _get_local_ips(self) -> list[str]:
        """Get all local IP addresses (IPv4 and IPv6)"""
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

        # If listen_addrs provided, use those; otherwise construct from local IPs
        if listen_addrs:
            multiaddrs = listen_addrs
        else:
            multiaddrs = []
            for ip in local_ips:
                if ":" in ip:
                    # IPv6
                    multiaddrs.append(f"/ip6/{ip}/tcp/{port}/p2p/{peer_id}")
                else:
                    # IPv4
                    multiaddrs.append(f"/ip4/{ip}/tcp/{port}/p2p/{peer_id}")

        # Add each multiaddr as a dnsaddr TXT record
        # Multiple dnsaddr attributes are allowed per spec
        for i, addr in enumerate(multiaddrs):
            if i == 0:
                properties[b"dnsaddr"] = addr.encode()
            else:
                properties[f"dnsaddr{i + 1}".encode()] = addr.encode()

        return properties

    def register(self) -> None:
        """Register the peer's mDNS service on the network."""
        try:
            self.zeroconf.register_service(self.service_info)
            logger.debug(f"mDNS service registered: {self.service_name}")
        except EventLoopBlocked as e:
            logger.warning(
                "EventLoopBlocked while registering mDNS '%s': %s", self.service_name, e
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

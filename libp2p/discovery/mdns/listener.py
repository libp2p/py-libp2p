import logging
import socket

from zeroconf import (
    ServiceBrowser,
    ServiceInfo,
    ServiceListener,
    Zeroconf,
)

from libp2p.abc import IPeerStore, Multiaddr
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("libp2p.discovery.mdns.listener")


class PeerListener(ServiceListener):
    """mDNS listener — now a true ServiceListener subclass."""

    def __init__(
        self,
        peerstore: IPeerStore,
        zeroconf: Zeroconf,
        service_type: str,
        service_name: str,
    ) -> None:
        self.peerstore = peerstore
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.service_name = service_name
        self.discovered_services: dict[str, ID] = {}
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener=self)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        if name == self.service_name:
            return
        logger.debug(f"Adding service: {name}")
        info = zc.get_service_info(type_, name, timeout=5000)
        if not info:
            return
        peer_info = self._extract_peer_info(info)
        if peer_info:
            self.discovered_services[name] = peer_info.peer_id
            self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.debug(f"Discovered Peer: {peer_info.peer_id}")

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        if name == self.service_name:
            return
        logger.debug(f"Removing service: {name}")
        peer_id = self.discovered_services.pop(name)
        self.peerstore.clear_addrs(peer_id)
        logger.debug(f"Removed Peer: {peer_id}")

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=5000)
        if not info:
            return
        peer_info = self._extract_peer_info(info)
        if peer_info:
            self.peerstore.clear_addrs(peer_info.peer_id)
            self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)
            logger.debug(f"Updated Peer {peer_info.peer_id}")

    def _extract_peer_info(self, info: ServiceInfo) -> PeerInfo | None:
        try:
            addrs = [
                Multiaddr(f"/ip4/{socket.inet_ntoa(addr)}/tcp/{info.port}")
                for addr in info.addresses
            ]
            pid_bytes = info.properties.get(b"id")
            if not pid_bytes:
                return None
            pid = ID.from_base58(pid_bytes.decode())
            return PeerInfo(peer_id=pid, addrs=addrs)
        except Exception:
            return None

    def stop(self) -> None:
        self.browser.cancel()

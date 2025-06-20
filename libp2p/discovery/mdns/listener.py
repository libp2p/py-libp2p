import socket
import time

from zeroconf import (
    ServiceBrowser,
    ServiceInfo,
    ServiceListener,
    ServiceStateChange,
    Zeroconf,
)

from libp2p.abc import IPeerStore
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


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
        self.discovered_services: set[str] = set()

        # pass `self` as the listener object
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener=self)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        # map to your on_service_state_change logic
        self._on_state_change(zc, type_, name, ServiceStateChange.Added)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._on_state_change(zc, type_, name, ServiceStateChange.Removed)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._on_state_change(zc, type_, name, ServiceStateChange.Updated)

    def _on_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state: ServiceStateChange,
    ) -> None:
        # skip our own service
        if name == self.service_name:
            return

        # handle Added
        if state is ServiceStateChange.Added:
            if name in self.discovered_services:
                return
            self.discovered_services.add(name)
            self._process_discovered_service(zeroconf, service_type, name)

        # ...optional hooks for Removed/Updated if you need them

    def _process_discovered_service(
        self, zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:
        # same retry logic you had before
        info = None
        for attempt in range(3):
            info = zeroconf.get_service_info(service_type, name, timeout=5000)
            if info:
                break
            time.sleep(1)

        if not info:
            return

        peer_info = self._extract_peer_info(info)
        if peer_info:
            # your existing hook
            self._handle_discovered_peer(peer_info)

    def _extract_peer_info(self, info: ServiceInfo) -> PeerInfo | None:
        try:
            addrs = [
                f"/ip4/{socket.inet_ntoa(addr)}/udp/{info.port}"
                for addr in info.addresses
            ]
            pid_bytes = info.properties.get(b"id")
            if not pid_bytes:
                return None
            pid = ID.from_base58(pid_bytes.decode())
            return PeerInfo(peer_id=pid, addrs=addrs)
        except Exception:
            return None

    def _handle_discovered_peer(self, peer_info: PeerInfo) -> None:
        # your “emit” or “connect” logic goes here
        # print("Discovered:", peer_info)
        print("Discovered:", peer_info.peer_id)

    def stop(self) -> None:
        self.browser.cancel()

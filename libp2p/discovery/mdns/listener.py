import logging
import socket
import time

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

logger = logging.getLogger(__name__)

META_QUERY_TYPE = "_services._dns-sd._udp.local."


class PeerListener(ServiceListener):
    """mDNS listener — ServiceListener subclass with async support."""

    def __init__(
        self,
        peerstore: IPeerStore,
        zeroconf: Zeroconf,
        service_type: str,
        service_name: str,
        ttl: int = 120,
        retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self.peerstore = peerstore
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.service_name = service_name
        self.ttl = ttl
        self.retry_attempts = retry_attempts
        self.retry_base_delay = retry_base_delay

        # Track discovered services with timestamps for cleanup
        self.discovered_services: dict[str, tuple[ID, float]] = {}
        self.meta_query_services: dict[str, str] = {}

        # Start browsers for both main service type and meta query
        self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener=self)
        self.meta_browser = ServiceBrowser(
            self.zeroconf, META_QUERY_TYPE, listener=self
        )

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a new service is discovered."""
        if name == self.service_name:
            return

        logger.debug(f"Adding service: {name} (type: {type_})")

        # Handle meta query responses
        if type_ == META_QUERY_TYPE:
            self._handle_meta_query(name)
            return

        info = self._get_service_info_with_retry(zc, type_, name)
        if not info:
            logger.warning(f"Failed to get service info for {name} after retries")
            return

        peer_info = self._extract_peer_info(info)
        if peer_info:
            self.discovered_services[name] = (peer_info.peer_id, time.time())
            self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, self.ttl)
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.debug(f"Discovered Peer: {peer_info.peer_id}")

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is removed."""
        if name == self.service_name:
            return

        logger.debug(f"Removing service: {name}")

        if name in self.discovered_services:
            peer_id, _ = self.discovered_services.pop(name)
            self.peerstore.clear_addrs(peer_id)
            logger.debug(f"Removed Peer: {peer_id}")

        # Also clean from meta query
        if name in self.meta_query_services:
            self.meta_query_services.pop(name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is updated."""
        if name == self.service_name:
            return

        info = self._get_service_info_with_retry(zc, type_, name)
        if not info:
            return

        peer_info = self._extract_peer_info(info)
        if peer_info:
            self.discovered_services[name] = (peer_info.peer_id, time.time())
            self.peerstore.clear_addrs(peer_info.peer_id)
            self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, self.ttl)
            logger.debug(f"Updated Peer {peer_info.peer_id}")

    def _get_service_info_with_retry(
        self, zc: Zeroconf, type_: str, name: str
    ) -> ServiceInfo | None:
        """Get service info with exponential backoff retry."""
        last_error = None

        for attempt in range(self.retry_attempts):
            try:
                info = zc.get_service_info(type_, name, timeout=5000)
                if info:
                    return info
                last_error = "No info returned"
            except Exception as e:
                last_error = str(e)

            if attempt < self.retry_attempts - 1:
                delay = self.retry_base_delay * (2**attempt)
                logger.debug(
                    f"Retry {attempt + 1}/{self.retry_attempts} "
                    f"for {name} after {delay}s: {last_error}"
                )
                time.sleep(delay)

        logger.warning(
            f"Failed to get service info for {name} after "
            f"{self.retry_attempts} attempts: {last_error}"
        )
        return None

    def _handle_meta_query(self, name: str) -> None:
        """Handle meta query response - tracks available service types."""
        logger.debug(f"Meta query discovered service type: {name}")
        self.meta_query_services[name] = name

    def _extract_peer_info(self, info: ServiceInfo) -> PeerInfo | None:
        """
        Extract peer info from ServiceInfo, parsing dnsaddr TXT records per spec.

        Per the libp2p mDNS spec, TXT records are the authoritative source of
        multiaddresses. A/AAAA records are ignored (go-libp2p behavior).
        """
        try:
            # Parse peer ID AND addresses from TXT dnsaddr records
            peer_id_str, addrs = self._parse_from_txt_records(info)
            if not peer_id_str or not addrs:
                logger.debug(f"No valid peer info in TXT records for {info.name}")
                return None

            # Validate peer ID format
            if not self._validate_peer_id(peer_id_str):
                logger.warning(f"Invalid peer ID format: {peer_id_str}")
                return None

            pid = ID.from_string(peer_id_str)
            return PeerInfo(peer_id=pid, addrs=addrs)
        except Exception as e:
            logger.debug(f"Failed to extract peer info from {info.name}: {e}")
            return None

    def _parse_from_txt_records(
        self, info: ServiceInfo
    ) -> tuple[str | None, list[Multiaddr]]:
        """
        Parse peer ID and addresses from TXT dnsaddr records.

        Spec: TXT record contains multiaddresses as dnsaddr=/.../p2p/QmId.
        We also support legacy 'id' property for backward compatibility.
        """
        peer_id = None
        addrs: list[Multiaddr] = []

        # Parse dnsaddr TXT records (spec-compliant)
        for key, value in info.properties.items():  # type: ignore[union-attr]
            if key.startswith(b"dnsaddr") and value is not None:
                addr_bytes: bytes = value
                try:
                    addr_str = addr_bytes.decode()
                    # Extract peer ID from /p2p/QmId
                    if "/p2p/" in addr_str:
                        candidate_id = addr_str.split("/p2p/")[-1]
                        if peer_id is None:
                            peer_id = candidate_id
                    # Parse the multiaddr (without /p2p/id suffix)
                    if "/p2p/" in addr_str:
                        ma_part = addr_str.split("/p2p/")[0]
                    else:
                        ma_part = addr_str
                    if ma_part:
                        addrs.append(Multiaddr(ma_part))
                except Exception:
                    continue

        # Fallback: legacy 'id' property (older implementations)
        if peer_id is None:
            pid_bytes = info.properties.get(b"id")
            if pid_bytes is not None:
                try:
                    peer_id = pid_bytes.decode()
                except Exception:
                    pass

        # If we have a peer_id from TXT but no addrs, try A/AAAA as fallback
        if peer_id and not addrs:
            for addr_bytes in info.addresses:
                try:
                    if len(addr_bytes) == 4:
                        ip = socket.inet_ntoa(addr_bytes)
                        addrs.append(Multiaddr(f"/ip4/{ip}/tcp/{info.port}"))
                    elif len(addr_bytes) == 16:
                        ip = socket.inet_ntop(socket.AF_INET6, addr_bytes)
                        addrs.append(Multiaddr(f"/ip6/{ip}/tcp/{info.port}"))
                except Exception:
                    continue

        return peer_id, addrs

    def _validate_peer_id(self, peer_id: str) -> bool:
        """
        Validate peer ID format using ID.from_string().

        Supports all key types (Qm, 12D3KooW, 4qB, etc.).
        """
        if not peer_id or not isinstance(peer_id, str):
            return False

        try:
            ID.from_string(peer_id)
            return True
        except Exception:
            return False

    def cleanup_stale_entries(self, max_age: int = 300) -> int:
        """
        Remove stale discovered service entries older than max_age seconds.

        Returns number of entries removed.
        """
        current_time = time.time()
        stale_keys = [
            name
            for name, (_, timestamp) in self.discovered_services.items()
            if current_time - timestamp > max_age
        ]

        for name in stale_keys:
            peer_id, _ = self.discovered_services.pop(name)
            self.peerstore.clear_addrs(peer_id)
            logger.debug(f"Cleaned up stale peer: {peer_id}")

        return len(stale_keys)

    def stop(self) -> None:
        """Stop the listener and clean up."""
        self.browser.cancel()
        self.meta_browser.cancel()
        self.discovered_services.clear()
        self.meta_query_services.clear()

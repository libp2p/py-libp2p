import time
import socket
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.id import ID

class PeerListener:
    """Enhanced mDNS listener for libp2p peer discovery."""
    
    def __init__(self, zeroconf: Zeroconf, service_type: str, service_name: str, on_peer_discovery=None):
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.service_name = service_name
        self.on_peer_discovery = on_peer_discovery
        self.discovered_services = set()
        self.browser = ServiceBrowser(
            self.zeroconf, self.service_type, handlers=[self.on_service_state_change]
        )

    def on_service_state_change(self, zeroconf: Zeroconf, service_type, name, state_change):
        if state_change != ServiceStateChange.Added or name == self.service_name or name in self.discovered_services:
            return
            
        print(f"Discovered service: {name}")
        self.discovered_services.add(name)
        
        # Process the discovered service
        self._process_discovered_service(zeroconf, service_type, name)

    def _process_discovered_service(self, zeroconf, service_type, name):
        # Try to get service info with retries
        info = None
        for attempt in range(3):
            info = zeroconf.get_service_info(service_type, name, timeout=5000)
            if info:
                print(f"Service info successfully retrieved for {name}")
                break
            print(f"Retrying service info retrieval (attempt {attempt + 1}/3)")
            time.sleep(1)

        if not info:
            print(f"Failed to retrieve service info for {name}")
            return

        # Extract peer information
        peer_info = self._extract_peer_info(info)
        print(f"Extracted peer info: {peer_info}")
        if peer_info:
            self._handle_discovered_peer(peer_info)

    def _extract_peer_info(self, service_info):
        try:
            # Extract IP addresses
            addresses = []
            for addr in service_info.addresses:
                ip = socket.inet_ntoa(addr)
                addresses.append(ip)
            
            # Extract port
            port = service_info.port
            
            # Extract peer ID from TXT record
            peer_id = None
            if service_info.properties:
                peer_id_bytes = service_info.properties.get(b'id')
                if peer_id_bytes:
                    peer_id = peer_id_bytes.decode('utf-8')
            
            if not peer_id:
                print(f"No peer ID found in TXT record for {service_info.name}")
                return None
            
            # Create multiaddresses
            multiaddrs = []
            for ip in addresses:
                multiaddr = f"/ip4/{ip}/udp/{port}"
                multiaddrs.append(multiaddr)
            
            # Create PeerInfo object
            peer_info = PeerInfo(
                peer_id=ID.from_base58(peer_id),
                addrs=multiaddrs
            )
            
            return peer_info
            
        except Exception as e:
            print(f"Error extracting peer info from {service_info.name}: {e}")
            return None

    def _handle_discovered_peer(self, peer_info):
        print(f"Successfully discovered peer: {peer_info.peer_id}")
        print(f"Peer addresses: {peer_info.addrs}")
        
        # Trigger callback if provided
        if self.on_peer_discovery:
            self.on_peer_discovery(peer_info)

    def stop(self):
        """Stop the listener."""
        if self.browser:
            self.browser.cancel()
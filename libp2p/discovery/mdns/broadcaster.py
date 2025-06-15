from zeroconf import Zeroconf, ServiceInfo
from .utils import stringGen
import socket

class PeerBroadcaster:
    """
    Broadcasts this peer's presence on the local network using mDNS/zeroconf.
    Registers a service with the peer's ID in the TXT record as per libp2p spec.
    """
    def __init__(self, zeroconf: Zeroconf, service_type: str, service_name: str, peer_id: str, port: int):
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.peer_id = peer_id
        self.port = port
        self.service_name = service_name
        
        # Get the local IP address
        local_ip = self._get_local_ip()
        
        self.service_info = ServiceInfo(
            type_=self.service_type,
            name=self.service_name,
            port=self.port,
            properties={b'id': self.peer_id.encode()},
            server=f"{self.service_name}",
            addresses=[socket.inet_aton(local_ip)]
        )

    def _get_local_ip(self):
        """Get the local IP address of this machine"""
        try:
            # Connect to a remote address to determine the local IP
            # This doesn't actually send data
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            return local_ip
        except Exception:
            # Fallback to localhost if we can't determine the IP
            return "127.0.0.1"

    def register(self):
        """Register the peer's mDNS service on the network."""
        print(f"Registering with name {self.service_name} and peer_id {self.peer_id} on port {self.port}")
        self.zeroconf.register_service(self.service_info)

    def unregister(self):
        """Unregister the peer's mDNS service from the network."""
        self.zeroconf.unregister_service(self.service_info)

"""
mDNS-based peer discovery for py-libp2p.
Conforms to https://github.com/libp2p/specs/blob/master/discovery/mdns.md
Uses zeroconf for mDNS broadcast/listen. Async operations use trio.
"""
import trio
from typing import Callable, Optional
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceStateChange
from .utils import (
    stringGen
)
from libp2p.abc import (
    INetworkService
)
from .listener import PeerListener
from .broadcaster import PeerBroadcaster
from libp2p.peer.peerinfo import PeerInfo

SERVICE_TYPE = "_p2p._udp.local."
MCAST_PORT = 5353
MCAST_ADDR = "224.0.0.251"

class MDNSDiscovery:
    """
    mDNS-based peer discovery for py-libp2p, using zeroconf.
    Conforms to the libp2p mDNS discovery spec.
    """
    def __init__(self, swarm: INetworkService, port: int = 8000, on_peer_discovery=None):
        self.peer_id = str(swarm.get_peer_id())
        self.port = port
        self.on_peer_discovery = on_peer_discovery
        self.zeroconf = Zeroconf()
        self.serviceName = f"{stringGen()}.{SERVICE_TYPE}"
        self.broadcaster = PeerBroadcaster(
            zeroconf=self.zeroconf,
            service_type=SERVICE_TYPE,
            service_name=self.serviceName,
            peer_id = self.peer_id,
            port = self.port
        )
        self.listener = PeerListener(
            zeroconf=self.zeroconf,
            service_type=SERVICE_TYPE,
            service_name=self.serviceName,
            on_peer_discovery=self.on_peer_discovery
        )

    def start(self):
        """Register this peer and start listening for others."""
        print(f"Starting mDNS discovery for peer {self.peer_id} on port {self.port}")
        self.broadcaster.register()
        # Listener is started in constructor

    def stop(self):
        """Unregister this peer and clean up zeroconf resources."""
        self.broadcaster.unregister()
        self.zeroconf.close()
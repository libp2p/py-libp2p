"""
mDNS-based peer discovery for py-libp2p.
Conforms to https://github.com/libp2p/specs/blob/master/discovery/mdns.md
Uses zeroconf for mDNS broadcast/listen. Async operations use trio.
"""

import logging

from zeroconf import (
    Zeroconf,
)

from libp2p.abc import (
    INetworkService,
)

from .broadcaster import (
    PeerBroadcaster,
)
from .listener import (
    PeerListener,
)
from .utils import (
    stringGen,
)

logger = logging.getLogger("libp2p.discovery.mdns")

SERVICE_TYPE = "_p2p._udp.local."
MCAST_PORT = 5353
MCAST_ADDR = "224.0.0.251"


class MDNSDiscovery:
    """
    mDNS-based peer discovery for py-libp2p, using zeroconf.
    Conforms to the libp2p mDNS discovery spec.
    """

    def __init__(self, swarm: INetworkService, port: int = 8000):
        self.peer_id = str(swarm.get_peer_id())
        self.port = port
        self.zeroconf = Zeroconf()
        self.serviceName = f"{stringGen()}.{SERVICE_TYPE}"
        self.peerstore = swarm.peerstore
        self.swarm = swarm
        self.broadcaster = PeerBroadcaster(
            zeroconf=self.zeroconf,
            service_type=SERVICE_TYPE,
            service_name=self.serviceName,
            peer_id=self.peer_id,
            port=self.port,
        )
        self.listener = PeerListener(
            zeroconf=self.zeroconf,
            peerstore=self.peerstore,
            service_type=SERVICE_TYPE,
            service_name=self.serviceName,
        )

    def start(self) -> None:
        """Register this peer and start listening for others."""
        logger.debug(
            f"Starting mDNS discovery for peer {self.peer_id} on port {self.port}"
        )
        self.broadcaster.register()
        # Listener is started in constructor

    def stop(self) -> None:
        """Unregister this peer and clean up zeroconf resources."""
        logger.debug("Stopping mDNS discovery")
        self.broadcaster.unregister()
        self.zeroconf.close()

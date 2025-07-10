import logging

from multiaddr import Multiaddr

from libp2p.abc import INetworkService
from libp2p.discovery.bootstrap.utils import validate_bootstrap_addresses
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.peer.peerinfo import info_from_p2p_addr

logger = logging.getLogger("libp2p.discovery.bootstrap")


class BootstrapDiscovery:
    """
    Bootstrap-based peer discovery for py-libp2p.
    Connects to predefined bootstrap peers and adds them to peerstore.
    """

    def __init__(self, swarm: INetworkService, bootstrap_addrs: list[str]):
        self.swarm = swarm
        self.peerstore = swarm.peerstore
        self.bootstrap_addrs = bootstrap_addrs or []
        self.discovered_peers: set[str] = set()

    async def start(self) -> None:
        """Process bootstrap addresses and emit peer discovery events."""
        logger.debug(
            f"Starting bootstrap discovery with "
            f"{len(self.bootstrap_addrs)} bootstrap addresses"
        )

        # Validate and filter bootstrap addresses
        self.bootstrap_addrs = validate_bootstrap_addresses(self.bootstrap_addrs)

        for addr_str in self.bootstrap_addrs:
            try:
                await self._process_bootstrap_addr(addr_str)
            except Exception as e:
                logger.debug(f"Failed to process bootstrap address {addr_str}: {e}")

    def stop(self) -> None:
        """Clean up bootstrap discovery resources."""
        logger.debug("Stopping bootstrap discovery")
        self.discovered_peers.clear()

    async def _process_bootstrap_addr(self, addr_str: str) -> None:
        """Convert string address to PeerInfo and add to peerstore."""
        try:
            multiaddr = Multiaddr(addr_str)
        except Exception as e:
            logger.debug(f"Invalid multiaddr format '{addr_str}': {e}")
            return
        if (self.is_dns_addr(multiaddr)):
            resolved_addrs = await multiaddr.resolve()
            for resolved_addr in resolved_addrs:
                if resolved_addr == multiaddr:
                    return
                self.add_addr(Multiaddr(resolved_addr)) 
        
        self.add_addr(multiaddr)

    def is_dns_addr(self, addr: Multiaddr) -> bool:
        """Check if the address is a DNS address."""
        return any(protocol.name == "dnsaddr" for protocol in addr.protocols())
    
    def add_addr(self, addr: Multiaddr) -> None:
        """Add a peer to the peerstore and emit discovery event."""
        # Extract peer info from multiaddr
        try:
            peer_info = info_from_p2p_addr(addr)
        except Exception as e:
            logger.debug(f"Failed to extract peer info from '{addr}': {e}")
            return

        # Skip if it's our own peer
        if peer_info.peer_id == self.swarm.get_peer_id():
            logger.debug(f"Skipping own peer ID: {peer_info.peer_id}")
            return

        # Skip if already discovered
        if str(peer_info.peer_id) in self.discovered_peers:
            logger.debug(f"Peer already discovered: {peer_info.peer_id}")
            return

        # Add to peerstore with TTL (using same pattern as mDNS)
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)

        # Track discovered peer
        self.discovered_peers.add(str(peer_info.peer_id))

        # Emit peer discovery event
        peerDiscovery.emit_peer_discovered(peer_info)
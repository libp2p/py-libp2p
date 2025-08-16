import logging

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver

from libp2p.abc import ID, INetworkService, PeerInfo
from libp2p.discovery.bootstrap.utils import validate_bootstrap_addresses
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.network.exceptions import SwarmException
from libp2p.peer.peerinfo import info_from_p2p_addr

logger = logging.getLogger("libp2p.discovery.bootstrap")
resolver = DNSResolver()


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
        if self.is_dns_addr(multiaddr):
            resolved_addrs = await resolver.resolve(multiaddr)
            peer_id_str = multiaddr.get_peer_id()
            if peer_id_str is None:
                logger.warning(f"Missing peer ID in DNS address: {addr_str}")
                return
            peer_id = ID.from_base58(peer_id_str)
            addrs = [addr for addr in resolved_addrs]
            if not addrs:
                logger.warning(f"No addresses resolved for DNS address: {addr_str}")
                return
            peer_info = PeerInfo(peer_id, addrs)
            await self.add_addr(peer_info)
        else:
            peer_info = info_from_p2p_addr(multiaddr)
            await self.add_addr(peer_info)

    def is_dns_addr(self, addr: Multiaddr) -> bool:
        """Check if the address is a DNS address."""
        return any(protocol.name == "dnsaddr" for protocol in addr.protocols())

    async def add_addr(self, peer_info: PeerInfo) -> None:
        """Add a peer to the peerstore, emit discovery event, and attempt connection."""
        # Skip if it's our own peer
        if peer_info.peer_id == self.swarm.get_peer_id():
            logger.debug(f"Skipping own peer ID: {peer_info.peer_id}")
            return

        # Always add addresses to peerstore (allows multiple addresses for same peer)
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)

        # Only emit discovery event if this is the first time we see this peer
        peer_id_str = str(peer_info.peer_id)
        if peer_id_str not in self.discovered_peers:
            # Track discovered peer
            self.discovered_peers.add(peer_id_str)
            # Emit peer discovery event
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.debug(f"Peer discovered: {peer_info.peer_id}")

            # Attempt to connect to the peer
            await self._connect_to_peer(peer_info.peer_id)
        else:
            logger.debug(f"Additional addresses added for peer: {peer_info.peer_id}")

    async def _connect_to_peer(self, peer_id: ID) -> None:
        """Attempt to establish a connection to a peer using swarm.dial_peer."""
        # Pre-connection validation: Check if already connected
        # This prevents duplicate connection attempts and unnecessary network overhead
        if peer_id in self.swarm.connections:
            logger.debug(
                f"Already connected to {peer_id} - skipping connection attempt"
            )
            return

        try:
            # Log connection attempt for monitoring and debugging
            logger.debug(f"Attempting to connect to {peer_id}")

            # Use swarm.dial_peer to establish connection
            await self.swarm.dial_peer(peer_id)

            # Post-connection validation: Verify connection was actually established
            # swarm.dial_peer may succeed but connection might not be in
            # connections dict
            # This can happen due to race conditions or connection cleanup
            if peer_id in self.swarm.connections:
                # Connection successfully established and registered
                # Log success at INFO level for operational visibility
                logger.info(f"Connected to {peer_id}")
            else:
                # Edge case: dial succeeded but connection not found
                # This indicates a potential issue with connection management
                logger.warning(f"Dial succeeded but connection not found for {peer_id}")

        except SwarmException as e:
            # Handle swarm-level connection errors
            logger.warning(f"Failed to connect to {peer_id}: {e}")

        except Exception as e:
            # Handle unexpected errors that aren't swarm-specific
            logger.error(f"Unexpected error connecting to {peer_id}: {e}")
            # Re-raise to allow caller to handle if needed
            raise

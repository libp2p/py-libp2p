import logging
import trio

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
    
    Uses Trio nurseries for parallel address resolution and connection attempts.
    Connects to predefined bootstrap peers and adds them to peerstore.
    """

    def __init__(self, swarm: INetworkService, bootstrap_addrs: list[str]):
        self.swarm = swarm
        self.peerstore = swarm.peerstore
        self.bootstrap_addrs = bootstrap_addrs or []
        self.discovered_peers: set[str] = set()

    async def start(self) -> None:
        """Process bootstrap addresses and emit peer discovery events in parallel."""
        logger.info(
            f"🚀 Starting bootstrap discovery with "
            f"{len(self.bootstrap_addrs)} bootstrap addresses"
        )
        
        # Show all bootstrap addresses being processed
        for i, addr in enumerate(self.bootstrap_addrs):
            logger.info(f"{i+1}. {addr}")

        # Allow other tasks to run
        await trio.lowlevel.checkpoint()

        # Validate and filter bootstrap addresses
        # self.bootstrap_addrs = validate_bootstrap_addresses(self.bootstrap_addrs)
        logger.info(f"Valid addresses after validation: {len(self.bootstrap_addrs)}")

        # Allow other tasks to run after validation
        await trio.lowlevel.checkpoint()

        # Use Trio nursery for PARALLEL address processing
        async with trio.open_nursery() as nursery:
            logger.info(f"Starting {len(self.bootstrap_addrs)} parallel address processing tasks")
            
            # Start all bootstrap address processing tasks in parallel
            for addr_str in self.bootstrap_addrs:
                logger.info(f"Starting parallel task for: {addr_str}")
                nursery.start_soon(self._process_bootstrap_addr_safe, addr_str)
            
            # The nursery will wait for all address processing tasks to complete
            logger.info("⏳ Nursery active - waiting for address processing tasks to complete")
        
        logger.info("✅ Bootstrap discovery startup complete - all tasks finished")

    def stop(self) -> None:
        """Clean up bootstrap discovery resources."""
        logger.debug("Stopping bootstrap discovery")
        self.discovered_peers.clear()

    async def _process_bootstrap_addr_safe(self, addr_str: str) -> None:
        """Safely process a bootstrap address with exception handling."""
        try:
            await self._process_bootstrap_addr(addr_str)
        except Exception as e:
            logger.debug(f"Failed to process bootstrap address {addr_str}: {e}")

    async def _process_bootstrap_addr(self, addr_str: str) -> None:
        """Convert string address to PeerInfo and add to peerstore."""
        try:
            multiaddr = Multiaddr(addr_str)
        except Exception as e:
            logger.debug(f"Invalid multiaddr format '{addr_str}': {e}")
            return
            
        if self.is_dns_addr(multiaddr):
            # Allow other tasks to run during DNS resolution
            await trio.lowlevel.checkpoint()
            
            resolved_addrs = await resolver.resolve(multiaddr)
            if resolved_addrs is None:
                logger.warning(f"DNS resolution returned None for: {addr_str}")
                return
            
            # Allow other tasks to run after DNS resolution
            await trio.lowlevel.checkpoint()
            
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
        """Add a peer to the peerstore, emit discovery event, and attempt connection in parallel."""
        logger.info(f"📥 Adding peer to peerstore: {peer_info.peer_id}")
        logger.info(f"📍 Total addresses received: {len(peer_info.addrs)}")
        
        # Skip if it's our own peer
        if peer_info.peer_id == self.swarm.get_peer_id():
            logger.debug(f"Skipping own peer ID: {peer_info.peer_id}")
            return
            
        # Always add addresses to peerstore with TTL=0 (no expiration)
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 0)

        # Allow other tasks to run after adding to peerstore
        await trio.lowlevel.checkpoint()

        # Verify addresses were added
        stored_addrs = self.peerstore.addrs(peer_info.peer_id)
        logger.info(f"✅ Addresses stored in peerstore: {len(stored_addrs)} addresses")

        # Only emit discovery event if this is the first time we see this peer
        peer_id_str = str(peer_info.peer_id)
        if peer_id_str not in self.discovered_peers:
            # Track discovered peer
            self.discovered_peers.add(peer_id_str)
            # Emit peer discovery event
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.debug(f"Peer discovered: {peer_info.peer_id}")

            # Use nursery for parallel connection attempt
            async with trio.open_nursery() as connection_nursery:
                logger.info(f"   🔌 Starting parallel connection attempt...")
                connection_nursery.start_soon(self._connect_to_peer, peer_info.peer_id)
                
        else:
            logger.debug(f"🔄 Additional addresses added for existing peer: {peer_info.peer_id}")
            # Even for existing peers, try to connect if not already connected
            if peer_info.peer_id not in self.swarm.connections:
                logger.info(f"🔌 Starting parallel connection attempt for existing peer...")
                # Use nursery for parallel connection
                async with trio.open_nursery() as connection_nursery:
                    connection_nursery.start_soon(self._connect_to_peer, peer_info.peer_id)

    async def _connect_to_peer(self, peer_id: ID) -> None:
        """Attempt to establish a connection to a peer using swarm.dial_peer."""
        logger.info(f"🔌 Connection attempt for peer: {peer_id}")
        
        # Pre-connection validation: Check if already connected
        if peer_id in self.swarm.connections:
            logger.debug(
                f"Already connected to {peer_id} - skipping connection attempt"
            )
            return

        # Allow other tasks to run before connection attempt
        await trio.lowlevel.checkpoint()

        # Check available addresses before attempting connection
        available_addrs = self.peerstore.addrs(peer_id)
        logger.info(f"📍 Available addresses for {peer_id}: {len(available_addrs)} addresses")
        
        if not available_addrs:
            logger.error(f"❌ No addresses available for {peer_id} - cannot connect")
            return

        try:
            # Log connection attempt for monitoring and debugging
            logger.debug(f"Attempting to connect to {peer_id}")

            # Use swarm.dial_peer to establish connection
            await self.swarm.dial_peer(peer_id)
            
            # Allow other tasks to run after dial attempt
            await trio.lowlevel.checkpoint()
            
            # Post-connection validation: Verify connection was actually established
            if peer_id in self.swarm.connections:
                logger.info(f"Connected to {peer_id}")
            else:
                logger.warning(f"Dial succeeded but connection not found for {peer_id}")

        except SwarmException as e:
            # Handle swarm-level connection errors
            logger.warning(f"Failed to connect to {peer_id}: {e}")

        except Exception as e:
            # Handle unexpected errors that aren't swarm-specific
            logger.error(f"Unexpected error connecting to {peer_id}: {e}")
            raise
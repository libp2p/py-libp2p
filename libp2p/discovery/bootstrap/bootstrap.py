import logging

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver
import trio

from libp2p.abc import ID, INetworkService, PeerInfo
from libp2p.discovery.bootstrap.utils import validate_bootstrap_addresses
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.network.exceptions import SwarmException
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.peerstore import PERMANENT_ADDR_TTL

logger = logging.getLogger("libp2p.discovery.bootstrap")
resolver = DNSResolver()

DEFAULT_CONNECTION_TIMEOUT = 10


class BootstrapDiscovery:
    """
    Bootstrap-based peer discovery for py-libp2p.
    Connects to predefined bootstrap peers and adds them to peerstore.
    """

    def __init__(self, swarm: INetworkService, bootstrap_addrs: list[str]):
        """
        Initialize BootstrapDiscovery.

        Args:
            swarm: The network service (swarm) instance
            bootstrap_addrs: List of bootstrap peer multiaddresses

        """
        self.swarm = swarm
        self.peerstore = swarm.peerstore
        self.bootstrap_addrs = bootstrap_addrs or []
        self.discovered_peers: set[str] = set()
        self.connection_timeout: int = DEFAULT_CONNECTION_TIMEOUT

    async def start(self) -> None:
        """Process bootstrap addresses and emit peer discovery events in parallel."""
        logger.info(
            f"Starting bootstrap discovery with "
            f"{len(self.bootstrap_addrs)} bootstrap addresses"
        )

        # Show all bootstrap addresses being processed
        for i, addr in enumerate(self.bootstrap_addrs):
            logger.debug(f"{i + 1}. {addr}")

        # Validate and filter bootstrap addresses
        self.bootstrap_addrs = validate_bootstrap_addresses(self.bootstrap_addrs)
        logger.info(f"Valid addresses after validation: {len(self.bootstrap_addrs)}")

        # Use Trio nursery for PARALLEL address processing
        try:
            async with trio.open_nursery() as nursery:
                logger.debug(
                    f"Starting {len(self.bootstrap_addrs)} parallel address "
                    f"processing tasks"
                )

                # Start all bootstrap address processing tasks in parallel
                for addr_str in self.bootstrap_addrs:
                    logger.debug(f"Starting parallel task for: {addr_str}")
                    nursery.start_soon(self._process_bootstrap_addr, addr_str)

                # The nursery will wait for all address processing tasks to complete
                logger.debug(
                    "Nursery active - waiting for address processing tasks to complete"
                )

        except trio.Cancelled:
            logger.debug("Bootstrap address processing cancelled - cleaning up tasks")
            raise
        except Exception as e:
            logger.error(f"Bootstrap address processing failed: {e}")
            raise

        logger.info("Bootstrap discovery startup complete - all tasks finished")

    def stop(self) -> None:
        """Clean up bootstrap discovery resources."""
        logger.info("Stopping bootstrap discovery and cleaning up tasks")

        # Clear discovered peers
        self.discovered_peers.clear()

        logger.debug("Bootstrap discovery cleanup completed")

    async def _process_bootstrap_addr(self, addr_str: str) -> None:
        """Convert string address to PeerInfo and add to peerstore."""
        try:
            try:
                multiaddr = Multiaddr(addr_str)
            except Exception as e:
                logger.debug(f"Invalid multiaddr format '{addr_str}': {e}")
                return

            if self.is_dns_addr(multiaddr):
                resolved_addrs = await resolver.resolve(multiaddr)
                if resolved_addrs is None:
                    logger.warning(f"DNS resolution returned None for: {addr_str}")
                    return

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
        except Exception as e:
            logger.warning(f"Failed to process bootstrap address {addr_str}: {e}")

    def is_dns_addr(self, addr: Multiaddr) -> bool:
        """Check if the address is a DNS address."""
        return any(protocol.name == "dnsaddr" for protocol in addr.protocols())

    async def add_addr(self, peer_info: PeerInfo) -> None:
        """
        Add a peer to the peerstore, emit discovery event,
        and attempt connection in parallel.
        """
        logger.debug(
            f"Adding peer {peer_info.peer_id} with {len(peer_info.addrs)} addresses"
        )

        # Skip if it's our own peer
        if peer_info.peer_id == self.swarm.get_peer_id():
            logger.debug(f"Skipping own peer ID: {peer_info.peer_id}")
            return

        # Filter addresses to only include IPv4+TCP (only supported protocol)
        ipv4_tcp_addrs = []
        filtered_out_addrs = []

        for addr in peer_info.addrs:
            if self._is_ipv4_tcp_addr(addr):
                ipv4_tcp_addrs.append(addr)
            else:
                filtered_out_addrs.append(addr)

        # Log filtering results
        logger.debug(
            f"Address filtering for {peer_info.peer_id}: "
            f"{len(ipv4_tcp_addrs)} IPv4+TCP, {len(filtered_out_addrs)} filtered"
        )

        # Skip peer if no IPv4+TCP addresses available
        if not ipv4_tcp_addrs:
            logger.warning(
                f"❌ No IPv4+TCP addresses for {peer_info.peer_id} - "
                f"skipping connection attempts"
            )
            return

        # Add only IPv4+TCP addresses to peerstore
        self.peerstore.add_addrs(peer_info.peer_id, ipv4_tcp_addrs, PERMANENT_ADDR_TTL)

        # Only emit discovery event if this is the first time we see this peer
        peer_id_str = str(peer_info.peer_id)
        if peer_id_str not in self.discovered_peers:
            # Track discovered peer
            self.discovered_peers.add(peer_id_str)
            # Emit peer discovery event
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.info(f"Peer discovered: {peer_info.peer_id}")

            # Connect to peer (parallel across different bootstrap addresses)
            logger.debug("Connecting to discovered peer...")
            await self._connect_to_peer(peer_info.peer_id)

        else:
            logger.debug(
                f"Additional addresses added for existing peer: {peer_info.peer_id}"
            )
            # Even for existing peers, try to connect if not already connected
            if peer_info.peer_id not in self.swarm.connections:
                logger.debug("Connecting to existing peer...")
                await self._connect_to_peer(peer_info.peer_id)

    async def _connect_to_peer(self, peer_id: ID) -> None:
        """
        Attempt to establish a connection to a peer with timeout.

        Uses swarm.dial_peer to connect using addresses stored in peerstore.
        Times out after self.connection_timeout seconds to prevent hanging.
        """
        logger.debug(f"Connection attempt for peer: {peer_id}")

        # Pre-connection validation: Check if already connected
        if peer_id in self.swarm.connections:
            logger.debug(
                f"Already connected to {peer_id} - skipping connection attempt"
            )
            return

        # Check available addresses before attempting connection
        available_addrs = self.peerstore.addrs(peer_id)
        logger.debug(f"Connecting to {peer_id} ({len(available_addrs)} addresses)")

        if not available_addrs:
            logger.error(f"❌ No addresses available for {peer_id} - cannot connect")
            return

        # Record start time for connection attempt monitoring
        connection_start_time = trio.current_time()

        try:
            with trio.move_on_after(self.connection_timeout):
                # Log connection attempt
                logger.debug(
                    f"Attempting connection to {peer_id} using "
                    f"{len(available_addrs)} addresses"
                )

                # Use swarm.dial_peer to connect using stored addresses
                await self.swarm.dial_peer(peer_id)

                # Calculate connection time
                connection_time = trio.current_time() - connection_start_time

                # Post-connection validation: Verify connection was actually established
                if peer_id in self.swarm.connections:
                    logger.info(
                        f"✅ Connected to {peer_id} (took {connection_time:.2f}s)"
                    )

                else:
                    logger.warning(
                        f"Dial succeeded but connection not found for {peer_id}"
                    )
        except trio.TooSlowError:
            logger.warning(
                f"❌ Connection to {peer_id} timed out after {self.connection_timeout}s"
            )
        except SwarmException as e:
            # Calculate failed connection time
            failed_connection_time = trio.current_time() - connection_start_time

            # Enhanced error logging
            error_msg = str(e)
            if "no addresses established a successful connection" in error_msg:
                logger.warning(
                    f"❌ Failed to connect to {peer_id} after trying all "
                    f"{len(available_addrs)} addresses "
                    f"(took {failed_connection_time:.2f}s)"
                )
                # Log individual address failures if this is a MultiError
                if (
                    e.__cause__ is not None
                    and hasattr(e.__cause__, "exceptions")
                    and getattr(e.__cause__, "exceptions", None) is not None
                ):
                    exceptions_list = getattr(e.__cause__, "exceptions")
                    logger.debug("📋 Individual address failure details:")
                    for i, addr_exception in enumerate(exceptions_list, 1):
                        logger.debug(f"Address {i}: {addr_exception}")
                        # Also log the actual address that failed
                        if i <= len(available_addrs):
                            logger.debug(f"Failed address: {available_addrs[i - 1]}")
                else:
                    logger.warning("No detailed exception information available")
            else:
                logger.warning(
                    f"❌ Failed to connect to {peer_id}: {e} "
                    f"(took {failed_connection_time:.2f}s)"
                )

        except Exception as e:
            # Handle unexpected errors that aren't swarm-specific
            failed_connection_time = trio.current_time() - connection_start_time
            logger.error(
                f"❌ Unexpected error connecting to {peer_id}: "
                f"{e} (took {failed_connection_time:.2f}s)"
            )
            # Don't re-raise to prevent killing the nursery and other parallel tasks

    def _is_ipv4_tcp_addr(self, addr: Multiaddr) -> bool:
        """
        Check if address is IPv4 with TCP protocol only.

        Filters out IPv6, UDP, QUIC, WebSocket, and other unsupported protocols.
        Only IPv4+TCP addresses are supported by the current transport.
        """
        try:
            protocols = addr.protocols()

            # Must have IPv4 protocol
            has_ipv4 = any(p.name == "ip4" for p in protocols)
            if not has_ipv4:
                return False

            # Must have TCP protocol
            has_tcp = any(p.name == "tcp" for p in protocols)
            if not has_tcp:
                return False

            return True

        except Exception:
            # If we can't parse the address, don't use it
            return False

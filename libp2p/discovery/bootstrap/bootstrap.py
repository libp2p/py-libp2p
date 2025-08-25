import logging

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver
import trio

from libp2p.abc import ID, INetworkService, PeerInfo
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.network.exceptions import SwarmException
from libp2p.peer.peerinfo import info_from_p2p_addr

logger = logging.getLogger("libp2p.discovery.bootstrap")
resolver = DNSResolver()


class BootstrapDiscovery:
    """
    Bootstrap-based peer discovery for py-libp2p.

    Processes bootstrap addresses in parallel and attempts initial connections.
    Adds discovered peers to peerstore for network bootstrapping.
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
        self.connection_timeout: int = 10
        self.connected_peers: set[ID] = (
            set()
        )  # Track connected peers for drop detection

    async def start(self) -> None:
        """Process bootstrap addresses and emit peer discovery events in parallel."""
        logger.info(
            f"Starting bootstrap discovery with "
            f"{len(self.bootstrap_addrs)} bootstrap addresses"
        )

        # Show all bootstrap addresses being processed
        for i, addr in enumerate(self.bootstrap_addrs):
            logger.info(f"{i + 1}. {addr}")

        # Allow other tasks to run
        await trio.lowlevel.checkpoint()

        # Validate and filter bootstrap addresses
        # self.bootstrap_addrs = validate_bootstrap_addresses(self.bootstrap_addrs)
        logger.info(f"Valid addresses after validation: {len(self.bootstrap_addrs)}")

        # Allow other tasks to run after validation
        await trio.lowlevel.checkpoint()

        # Use Trio nursery for PARALLEL address processing
        try:
            async with trio.open_nursery() as nursery:
                logger.info(
                    f"Starting {len(self.bootstrap_addrs)} parallel address "
                    f"processing tasks"
                )

                # Start all bootstrap address processing tasks in parallel
                for addr_str in self.bootstrap_addrs:
                    logger.info(f"Starting parallel task for: {addr_str}")
                    nursery.start_soon(self._process_bootstrap_addr, addr_str)

                # The nursery will wait for all address processing tasks to complete
                logger.info(
                    "Nursery active - waiting for address processing tasks to complete"
                )

        except trio.Cancelled:
            logger.info("Bootstrap address processing cancelled - cleaning up tasks")
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
        self.connected_peers.clear()

        logger.debug("Bootstrap discovery cleanup completed")

    async def _process_bootstrap_addr_safe(self, addr_str: str) -> None:
        """Safely process a bootstrap address with exception handling."""
        try:
            await self._process_bootstrap_addr(addr_str)
        except Exception as e:
            logger.warning(f"Failed to process bootstrap address {addr_str}: {e}")
            # Ensure task cleanup and continue processing other addresses

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
        """
        Add a peer to the peerstore, emit discovery event,
        and attempt connection in parallel.
        """
        logger.info(f"Adding peer to peerstore: {peer_info.peer_id}")
        logger.info(f"Total addresses received: {len(peer_info.addrs)}")

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
        logger.info(f"Address filtering for {peer_info.peer_id}:")
        logger.info(f"IPv4+TCP addresses: {len(ipv4_tcp_addrs)}")
        logger.info(f"Filtered out: {len(filtered_out_addrs)} (unsupported protocols)")

        # Show filtered addresses for debugging
        if filtered_out_addrs:
            for addr in filtered_out_addrs:
                logger.debug(f"Filtered: {addr}")

        # Show addresses that will be used
        if ipv4_tcp_addrs:
            logger.debug("Usable addresses:")
            for i, addr in enumerate(ipv4_tcp_addrs, 1):
                logger.debug(f"   Address {i}: {addr}")

        # Skip peer if no IPv4+TCP addresses available
        if not ipv4_tcp_addrs:
            logger.warning(
                f"❌ No IPv4+TCP addresses for {peer_info.peer_id} - "
                f"skipping connection attempts"
            )
            return

        logger.info(
            f"Will attempt connection using {len(ipv4_tcp_addrs)} IPv4+TCP addresses"
        )

        # Add only IPv4+TCP addresses to peerstore
        self.peerstore.add_addrs(peer_info.peer_id, ipv4_tcp_addrs, 0)

        # Allow other tasks to run after adding to peerstore
        await trio.lowlevel.checkpoint()

        # Verify addresses were added
        stored_addrs = self.peerstore.addrs(peer_info.peer_id)
        logger.info(f"Addresses stored in peerstore: {len(stored_addrs)} addresses")

        # Only emit discovery event if this is the first time we see this peer
        peer_id_str = str(peer_info.peer_id)
        if peer_id_str not in self.discovered_peers:
            # Track discovered peer
            self.discovered_peers.add(peer_id_str)
            # Emit peer discovery event
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.debug(f"Peer discovered: {peer_info.peer_id}")

            # Use nursery for parallel connection attempt (non-blocking)
            try:
                async with trio.open_nursery() as connection_nursery:
                    logger.info("Starting parallel connection attempt...")
                    connection_nursery.start_soon(
                        self._connect_to_peer, peer_info.peer_id
                    )
            except trio.Cancelled:
                logger.debug(f"Connection attempt cancelled for {peer_info.peer_id}")
                raise
            except Exception as e:
                logger.warning(
                    f"Connection nursery failed for {peer_info.peer_id}: {e}"
                )

        else:
            logger.debug(
                f"Additional addresses added for existing peer: {peer_info.peer_id}"
            )
            # Even for existing peers, try to connect if not already connected
            if peer_info.peer_id not in self.swarm.connections:
                logger.info("Starting parallel connection attempt for existing peer...")
                # Use nursery for parallel connection attempt (non-blocking)
                try:
                    async with trio.open_nursery() as connection_nursery:
                        connection_nursery.start_soon(
                            self._connect_to_peer, peer_info.peer_id
                        )
                except trio.Cancelled:
                    logger.debug(
                        f"Connection attempt cancelled for existing peer "
                        f"{peer_info.peer_id}"
                    )
                    raise
                except Exception as e:
                    logger.warning(
                        f"Connection nursery failed for existing peer "
                        f"{peer_info.peer_id}: {e}"
                    )

    async def _connect_to_peer(self, peer_id: ID) -> None:
        """
        Attempt to establish a connection to a peer with timeout.

        Uses swarm.dial_peer to connect using addresses stored in peerstore.
        Times out after connection_timeout seconds to prevent hanging.
        """
        logger.info(f"Connection attempt for peer: {peer_id}")

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
        logger.info(
            f"Available addresses for {peer_id}: {len(available_addrs)} addresses"
        )

        # Log all available addresses for transparency
        for i, addr in enumerate(available_addrs, 1):
            logger.debug(f"  Address {i}: {addr}")

        if not available_addrs:
            logger.error(f"❌ No addresses available for {peer_id} - cannot connect")
            return

        # Record start time for connection attempt monitoring
        connection_start_time = trio.current_time()

        try:
            with trio.move_on_after(self.connection_timeout):
                # Log connection attempt
                logger.info(
                    f"Attempting connection to {peer_id} using "
                    f"{len(available_addrs)} addresses"
                )

                # Log each address that will be attempted
                for i, addr in enumerate(available_addrs, 1):
                    logger.debug(f"Address {i}: {addr}")

                # Use swarm.dial_peer to connect using stored addresses
                connection = await self.swarm.dial_peer(peer_id)

                # Calculate connection time
                connection_time = trio.current_time() - connection_start_time

                # Allow other tasks to run after dial attempt
                await trio.lowlevel.checkpoint()

                # Post-connection validation: Verify connection was actually established
                if peer_id in self.swarm.connections:
                    logger.info(
                        f"✅ Connected to {peer_id} (took {connection_time:.2f}s)"
                    )

                    # Track this connection for drop monitoring
                    self.connected_peers.add(peer_id)

                    # Start monitoring this specific connection for drops
                    trio.lowlevel.spawn_system_task(
                        self._monitor_peer_connection, peer_id
                    )

                    # Log which address was successful (if available)
                    if hasattr(connection, "get_transport_addresses"):
                        successful_addrs = connection.get_transport_addresses()
                        if successful_addrs:
                            logger.debug(f"Successful address: {successful_addrs[0]}")
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
                    logger.info("📋 Individual address failure details:")
                    for i, addr_exception in enumerate(exceptions_list, 1):
                        logger.info(f"Address {i}: {addr_exception}")
                        # Also log the actual address that failed
                        if i <= len(available_addrs):
                            logger.info(f"Failed address: {available_addrs[i - 1]}")
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
            logger.debug("Continuing with other parallel connection attempts")

    async def _monitor_peer_connection(self, peer_id: ID) -> None:
        """
        Monitor a specific peer connection for drops using event-driven detection.

        Waits for the connection to be removed from swarm.connections, which
        happens when error 4101 or other connection errors occur.
        """
        logger.debug(f"🔍 Started monitoring connection to {peer_id}")

        try:
            # Wait for the connection to disappear (event-driven)
            while peer_id in self.swarm.connections:
                await trio.sleep(0.1)  # Small sleep to yield control

            # Connection was dropped - log it immediately
            if peer_id in self.connected_peers:
                self.connected_peers.discard(peer_id)
                logger.warning(
                    f"📡 Connection to {peer_id} was dropped! (detected event-driven)"
                )

                # Log current connection count
                remaining_connections = len(self.connected_peers)
                logger.info(f"📊 Remaining connected peers: {remaining_connections}")

        except trio.Cancelled:
            logger.debug(f"Connection monitoring for {peer_id} stopped")
        except Exception as e:
            logger.error(f"Error monitoring connection to {peer_id}: {e}")
            # Clean up tracking on error
            self.connected_peers.discard(peer_id)

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

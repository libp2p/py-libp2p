import logging

from multiaddr import Multiaddr
from multiaddr.protocols import P_IP4, P_IP6, P_TCP
from multiaddr.resolvers import DNSResolver
import trio

from libp2p.abc import ID, INetworkService, PeerInfo
from libp2p.discovery.bootstrap.utils import validate_bootstrap_addresses
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.network.exceptions import SwarmException
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.peerstore import PERMANENT_ADDR_TTL
from libp2p.utils.dns_utils import (
    DNSResolutionMetrics,
    resolve_multiaddr_with_retry,
)

logger = logging.getLogger(__name__)
resolver = DNSResolver()

DEFAULT_CONNECTION_TIMEOUT = 10


class BootstrapDiscovery:
    """
    Bootstrap-based peer discovery for py-libp2p.
    Connects to predefined bootstrap peers and adds them to peerstore.
    """

    def __init__(
        self,
        swarm: INetworkService,
        bootstrap_addrs: list[str],
        *,
        allow_ipv6: bool = False,
        dns_resolution_timeout: float = 10.0,
        dns_max_retries: int = 3,
        dns_metrics: DNSResolutionMetrics | None = None,
    ):
        """
        Initialize BootstrapDiscovery.

        Args:
            swarm: The network service (swarm) instance
            bootstrap_addrs: List of bootstrap peer multiaddresses
            allow_ipv6: If True, accept IPv6+TCP addresses in addition to IPv4+TCP
                (enable when handshake/transport supports IPv6).
            dns_resolution_timeout: Timeout in seconds per DNS resolution attempt.
            dns_max_retries: Max DNS resolution attempts (with backoff) per address.
            dns_metrics: Optional metrics to record DNS success/failure counts.

        """
        self.swarm = swarm
        self.peerstore = swarm.peerstore
        self.bootstrap_addrs = bootstrap_addrs or []
        self.discovered_peers: set[str] = set()
        self.connection_timeout: int = DEFAULT_CONNECTION_TIMEOUT
        self.allow_ipv6 = allow_ipv6
        self.dns_resolution_timeout = dns_resolution_timeout
        self.dns_max_retries = dns_max_retries
        self.dns_metrics = dns_metrics

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
                resolved_addrs = await resolve_multiaddr_with_retry(
                    multiaddr,
                    resolver=resolver,
                    max_retries=self.dns_max_retries,
                    timeout_seconds=self.dns_resolution_timeout,
                    metrics=self.dns_metrics,
                )
                if not resolved_addrs:
                    logger.warning(
                        "No addresses resolved for DNS address: %s", addr_str
                    )
                    return

                peer_id_str = multiaddr.get_peer_id()
                if peer_id_str is None:
                    logger.warning("Missing peer ID in DNS address: %s", addr_str)
                    return
                peer_id = ID.from_base58(peer_id_str)
                peer_info = PeerInfo(peer_id, list(resolved_addrs))
                await self.add_addr(peer_info)
            else:
                peer_info = info_from_p2p_addr(multiaddr)
                await self.add_addr(peer_info)
        except Exception as e:
            logger.warning(f"Failed to process bootstrap address {addr_str}: {e}")

    def is_dns_addr(self, addr: Multiaddr) -> bool:
        """Check if the address is a DNS address (dns, dns4, dns6, or dnsaddr)."""
        dns_protocols = {"dns", "dns4", "dns6", "dnsaddr"}
        return any(protocol.name in dns_protocols for protocol in addr.protocols())

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

        # Filter addresses to supported protocols (IPv4+TCP; IPv6+TCP if allow_ipv6)
        supported_addrs: list[Multiaddr] = []
        filtered_out_addrs: list[Multiaddr] = []

        for addr in peer_info.addrs:
            if self._is_supported_addr(addr):
                supported_addrs.append(addr)
            else:
                filtered_out_addrs.append(addr)

        # Log filtering results
        logger.debug(
            "Address filtering for %s: %s supported, %s filtered",
            peer_info.peer_id,
            len(supported_addrs),
            len(filtered_out_addrs),
        )

        # Skip peer if no supported addresses available
        if not supported_addrs:
            logger.warning(
                "No supported (IPv4+TCP or IPv6+TCP) addresses for %s - "
                "skipping connection attempts",
                peer_info.peer_id,
            )
            return

        # Add only supported addresses to peerstore
        self.peerstore.add_addrs(peer_info.peer_id, supported_addrs, PERMANENT_ADDR_TTL)

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

    def _is_supported_addr(self, addr: Multiaddr) -> bool:
        """
        Check if address is IPv4+TCP or (when allow_ipv6) IPv6+TCP.

        Filters out UDP, QUIC, WebSocket, and other unsupported protocols.
        Uses protocol codes for type-safe comparison.
        When allow_ipv6 is True, IPv6+TCP is accepted (for when handshake supports it).
        """
        try:
            protocols = list(addr.protocols())

            # Must have TCP protocol (by code)
            has_tcp = any(p.code == P_TCP for p in protocols)
            if not has_tcp:
                return False

            # IPv4+TCP always supported
            if any(p.code == P_IP4 for p in protocols):
                return True
            # IPv6+TCP supported only when allow_ipv6 is True (handshake allows)
            if self.allow_ipv6 and any(p.code == P_IP6 for p in protocols):
                return True

            return False

        except Exception:
            # If we can't parse the address, don't use it
            return False

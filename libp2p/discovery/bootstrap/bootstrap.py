import logging

from multiaddr import Multiaddr
from multiaddr.resolvers import DNSResolver
import trio

from libp2p.abc import ID, INetworkService, PeerInfo
from libp2p.discovery.bootstrap.utils import validate_bootstrap_addresses
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.network.exceptions import SwarmDialAllFailedError, SwarmException
from libp2p.peer.peerinfo import InvalidAddrError, info_from_p2p_addr
from libp2p.peer.peerstore import PERMANENT_ADDR_TTL
from libp2p.utils.dns_utils import (
    DNSResolutionMetrics,
    resolve_multiaddr_with_retry,
)

logger = logging.getLogger(__name__)
resolver = DNSResolver()

DEFAULT_CONNECTION_TIMEOUT = 10.0

# go-libp2p spec: default interval between bootstrap reconnections (seconds).
DEFAULT_RECONNECT_INTERVAL = 10.0

# go-libp2p spec: max consecutive failures before removing a bootstrap peer.
MAX_CONSECUTIVE_FAILURES = 3


class BootstrapDiscovery:
    """
    Bootstrap-based peer discovery for py-libp2p.

    Connects to predefined bootstrap peers, adds them to the peerstore,
    and periodically reconnects to maintain connectivity (go-libp2p spec).

    Spec reference: https://github.com/libp2p/specs/blob/master/peer-discovery/README.md
    """

    def __init__(
        self,
        swarm: INetworkService,
        bootstrap_addrs: list[str],
        *,
        allow_ipv6: bool = False,
        connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
        dns_resolution_timeout: float = 10.0,
        dns_max_retries: int = 3,
        dns_metrics: DNSResolutionMetrics | None = None,
        reconnect_interval: float = DEFAULT_RECONNECT_INTERVAL,
    ):
        """
        Initialize BootstrapDiscovery.

        Args:
            swarm: The network service (swarm) instance
            bootstrap_addrs: List of bootstrap peer multiaddresses
            allow_ipv6: If True, accept IPv6+TCP addresses in addition to IPv4+TCP
                (enable when handshake/transport supports IPv6).
            connection_timeout: Timeout in seconds for connecting to a peer.
            dns_resolution_timeout: Timeout in seconds per DNS resolution attempt.
            dns_max_retries: Max DNS resolution attempts (with backoff) per address.
            dns_metrics: Optional metrics to record DNS success/failure counts.
            reconnect_interval: Seconds between periodic reconnection attempts
                to bootstrap peers (go-libp2p spec compliance).

        """
        self.swarm = swarm
        self.peerstore = swarm.peerstore
        self.bootstrap_addrs = bootstrap_addrs or []
        self.original_addrs: list[str] = list(self.bootstrap_addrs)
        self.discovered_peers: set[str] = set()
        self.connection_timeout: float = connection_timeout
        self.allow_ipv6: bool = allow_ipv6
        self.dns_resolution_timeout: float = dns_resolution_timeout
        self.dns_max_retries: int = dns_max_retries
        self.dns_metrics: DNSResolutionMetrics | None = dns_metrics
        self.reconnect_interval: float = reconnect_interval
        # go-libp2p spec: track consecutive failures per peer for removal.
        self._failure_counts: dict[str, int] = {}
        self._reconnect_scope: trio.CancelScope | None = None

    async def start(self) -> None:
        """Process bootstrap addresses and emit peer discovery events in parallel."""
        logger.info(
            "Starting bootstrap discovery with %d bootstrap addresses",
            len(self.bootstrap_addrs),
        )

        for i, addr in enumerate(self.bootstrap_addrs):
            logger.debug("%d. %s", i + 1, addr)

        self.bootstrap_addrs = validate_bootstrap_addresses(self.bootstrap_addrs)
        logger.info("Valid addresses after validation: %d", len(self.bootstrap_addrs))

        await self._process_all_addrs()

        # go-libp2p spec: start periodic reconnection loop.
        self._reconnect_scope = trio.CancelScope()
        trio.lowlevel.spawn_system_task(
            self._periodic_reconnect,
            self._reconnect_scope,
        )
        logger.info("Bootstrap discovery startup complete")

    def stop(self) -> None:
        """Clean up bootstrap discovery resources."""
        logger.info("Stopping bootstrap discovery and cleaning up tasks")

        # Cancel periodic reconnection.
        if self._reconnect_scope is not None:
            self._reconnect_scope.cancel()
            self._reconnect_scope = None

        # Clear state for clean restart.
        self.discovered_peers.clear()
        self._failure_counts.clear()
        self.bootstrap_addrs = list(self.original_addrs)

        logger.debug("Bootstrap discovery cleanup completed")

    async def _process_all_addrs(self) -> None:
        """Process all bootstrap addresses in parallel via a nursery."""
        try:
            async with trio.open_nursery() as nursery:
                for addr_str in self.bootstrap_addrs:
                    nursery.start_soon(self._process_bootstrap_addr, addr_str)
        except trio.Cancelled:
            raise
        except Exception as e:
            logger.error("Bootstrap address processing failed: %s", e)
            raise

    async def _periodic_reconnect(self, scope: trio.CancelScope) -> None:
        """go-libp2p spec: periodically reconnect to bootstrap peers."""
        with scope:
            while True:
                try:
                    await trio.sleep(self.reconnect_interval)
                except trio.Cancelled:
                    raise

                # Only reconnect to peers we've discovered but lost connection to.
                peers_to_reconnect = [
                    pid_str
                    for pid_str in self.discovered_peers
                    if self._peer_id_from_str(pid_str) not in self.swarm.connections
                ]

                if not peers_to_reconnect:
                    continue

                logger.debug(
                    "Periodic reconnect: %d disconnected bootstrap peers",
                    len(peers_to_reconnect),
                )

                try:
                    async with trio.open_nursery() as nursery:
                        for pid_str in peers_to_reconnect:
                            peer_id = self._peer_id_from_str(pid_str)
                            nursery.start_soon(self._connect_to_peer, peer_id)
                except trio.Cancelled:
                    raise
                except Exception as e:
                    logger.debug("Periodic reconnect batch failed: %s", e)

    def _peer_id_from_str(self, peer_id_str: str) -> ID:
        """Convert a base58 peer ID string back to an ID object."""
        return ID.from_string(peer_id_str)

    async def _process_bootstrap_addr(self, addr_str: str) -> None:
        """Convert string address to PeerInfo and add to peerstore."""
        try:
            try:
                multiaddr = Multiaddr(addr_str)
            except (ValueError, TypeError) as e:
                logger.debug("Invalid multiaddr format '%s': %s", addr_str, e)
                return

            if self.is_dns_addr(multiaddr):
                await self._process_dns_addr(multiaddr, addr_str)
            else:
                peer_info = info_from_p2p_addr(multiaddr)
                await self.add_addr(peer_info)
        except InvalidAddrError as e:
            logger.warning("Invalid bootstrap address %s: %s", addr_str, e)
        except (SwarmException, trio.TooSlowError) as e:
            logger.warning("Failed to process bootstrap address %s: %s", addr_str, e)
        except Exception as e:
            logger.warning("Failed to process bootstrap address %s: %s", addr_str, e)

    async def _process_dns_addr(self, multiaddr: Multiaddr, addr_str: str) -> None:
        """Resolve a DNS bootstrap address and process the resolved IPs."""
        resolved_addrs = await resolve_multiaddr_with_retry(
            multiaddr,
            resolver=resolver,
            max_retries=self.dns_max_retries,
            timeout_seconds=self.dns_resolution_timeout,
            metrics=self.dns_metrics,
        )
        if not resolved_addrs:
            logger.warning("No addresses resolved for DNS address: %s", addr_str)
            return

        peer_id_str = multiaddr.get_peer_id()
        if peer_id_str is None:
            logger.warning("Missing peer ID in DNS address: %s", addr_str)
            return
        peer_id = ID.from_string(peer_id_str)

        # go-libp2p AddrInfoFromP2pAddr: strip /p2p/ from resolved addresses.
        p2p_suffix = Multiaddr(f"/p2p/{peer_id_str}")
        decapsulated_addrs: list[Multiaddr] = []
        for resolved_addr in resolved_addrs:
            try:
                decapsulated = resolved_addr.decapsulate(p2p_suffix)
                if decapsulated is not None and len(decapsulated.protocols()) > 0:
                    decapsulated_addrs.append(decapsulated)
                else:
                    decapsulated_addrs.append(resolved_addr)
            except ValueError:
                decapsulated_addrs.append(resolved_addr)

        peer_info = PeerInfo(peer_id, decapsulated_addrs)
        await self.add_addr(peer_info)

    @staticmethod
    def is_dns_addr(addr: Multiaddr) -> bool:
        """Check if the address is a DNS address (dns, dns4, dns6, or dnsaddr)."""
        dns_protocols = {"dns", "dns4", "dns6", "dnsaddr"}
        return any(protocol.name in dns_protocols for protocol in addr.protocols())

    async def add_addr(self, peer_info: PeerInfo) -> None:
        """
        Add a peer to the peerstore, emit discovery event,
        and attempt connection in parallel.
        """
        logger.debug(
            "Adding peer %s with %d addresses",
            peer_info.peer_id,
            len(peer_info.addrs),
        )

        # Skip if it's our own peer.
        if peer_info.peer_id == self.swarm.get_peer_id():
            logger.debug("Skipping own peer ID: %s", peer_info.peer_id)
            return

        # Filter addresses to supported protocols.
        supported_addrs: list[Multiaddr] = []
        for addr in peer_info.addrs:
            if self._is_supported_addr(addr, self.allow_ipv6):
                supported_addrs.append(addr)

        if not supported_addrs:
            logger.warning(
                "No supported addresses for %s - skipping", peer_info.peer_id
            )
            return

        # Add supported addresses to peerstore.
        self.peerstore.add_addrs(peer_info.peer_id, supported_addrs, PERMANENT_ADDR_TTL)

        # Deduplicate: only emit discovery event for new peers.
        peer_id_str = str(peer_info.peer_id)
        if peer_id_str not in self.discovered_peers:
            self.discovered_peers.add(peer_id_str)
            peerDiscovery.emit_peer_discovered(peer_info)
            logger.info("Peer discovered: %s", peer_info.peer_id)
            await self._connect_to_peer(peer_info.peer_id)
        else:
            logger.debug(
                "Additional addresses for existing peer: %s", peer_info.peer_id
            )
            if peer_info.peer_id not in self.swarm.connections:
                await self._connect_to_peer(peer_info.peer_id)

    async def _connect_to_peer(self, peer_id: ID) -> None:
        """
        Attempt to establish a connection to a peer with timeout.

        go-libp2p spec: tracks consecutive failures and removes unreachable
        bootstrap peers after MAX_CONSECUTIVE_FAILURES.
        """
        peer_id_str = str(peer_id)

        # Skip if already connected.
        if peer_id in self.swarm.connections:
            return

        available_addrs = self.peerstore.addrs(peer_id)
        if not available_addrs:
            self._record_failure(peer_id_str)
            return

        connection_start_time = trio.current_time()

        try:
            with trio.fail_after(self.connection_timeout):
                await self.swarm.dial_peer(peer_id)

                connection_time = trio.current_time() - connection_start_time
                if peer_id in self.swarm.connections:
                    logger.info(
                        "Connected to %s (took %.2fs)", peer_id, connection_time
                    )
                    # go-libp2p spec: reset failure count on success.
                    self._failure_counts.pop(peer_id_str, None)
                else:
                    logger.warning(
                        "Dial succeeded but connection not found for %s", peer_id
                    )
                    self._record_failure(peer_id_str)

        except trio.TooSlowError:
            logger.warning(
                "Connection to %s timed out after %.1fs",
                peer_id,
                self.connection_timeout,
            )
            self._record_failure(peer_id_str)

        except SwarmDialAllFailedError as e:
            failed_connection_time = trio.current_time() - connection_start_time
            logger.warning(
                "Failed to connect to %s after trying all %d addresses (took %.2fs)",
                peer_id,
                len(available_addrs),
                failed_connection_time,
            )
            if (
                e.__cause__ is not None
                and hasattr(e.__cause__, "exceptions")
                and getattr(e.__cause__, "exceptions", None) is not None
            ):
                for i, addr_exception in enumerate(
                    getattr(e.__cause__, "exceptions"), 1
                ):
                    logger.debug("Address %d: %s", i, addr_exception)
                    if i <= len(available_addrs):
                        logger.debug("Failed address: %s", available_addrs[i - 1])
            self._record_failure(peer_id_str)

        except SwarmException as e:
            failed_connection_time = trio.current_time() - connection_start_time
            logger.warning(
                "Failed to connect to %s: %s (took %.2fs)",
                peer_id,
                e,
                failed_connection_time,
            )
            self._record_failure(peer_id_str)

        except Exception as e:
            failed_connection_time = trio.current_time() - connection_start_time
            logger.error(
                "Unexpected error connecting to %s: %s (took %.2fs)",
                peer_id,
                e,
                failed_connection_time,
            )

    def _record_failure(self, peer_id_str: str) -> None:
        """
        go-libp2p spec: track consecutive failures and remove unreachable
        bootstrap peers after MAX_CONSECUTIVE_FAILURES.
        """
        count = self._failure_counts.get(peer_id_str, 0) + 1
        self._failure_counts[peer_id_str] = count

        if count >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "Bootstrap peer %s failed %d consecutive times - removing",
                peer_id_str,
                count,
            )
            self._remove_bootstrap_peer(peer_id_str)

    def _remove_bootstrap_peer(self, peer_id_str: str) -> None:
        """
        go-libp2p spec: remove a bootstrap peer that has failed too many times.
        Clears addresses from peerstore and removes from discovered set.
        """
        peer_id = self._peer_id_from_str(peer_id_str)
        self.peerstore.clear_addrs(peer_id)
        self.discovered_peers.discard(peer_id_str)
        self._failure_counts.pop(peer_id_str, None)
        # Remove from bootstrap_addrs so it's not re-processed on reconnect.
        p2p_component = f"/p2p/{peer_id_str}"
        self.bootstrap_addrs = [
            a for a in self.bootstrap_addrs if not a.endswith(p2p_component)
        ]

    @staticmethod
    def _is_supported_addr(addr: Multiaddr, allow_ipv6: bool = False) -> bool:
        """
        Check if address contains a supported transport protocol and IP version.

        Accepts TCP, QUIC, QUIC-v1, WebSockets (ws, wss).
        IPv4 addresses are always accepted. IPv6 addresses are accepted
        only when allow_ipv6 is True.
        """
        try:
            proto_names = {p.name for p in addr.protocols()}
            supported_transports = {"tcp", "quic", "quic-v1", "ws", "wss"}

            if proto_names.intersection(supported_transports):
                if "ip6" in proto_names and not allow_ipv6:
                    logger.debug(
                        "Filtering out IPv6 address (allow_ipv6=False): %s", addr
                    )
                    return False
                return True

            return False

        except Exception:
            return False

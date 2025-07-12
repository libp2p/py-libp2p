"""
NAT traversal utilities for libp2p.

This module provides utilities for NAT traversal and reachability detection.
"""

import ipaddress
import logging

from multiaddr import (
    Multiaddr,
)

from libp2p.abc import (
    IHost,
    INetConn,
)
from libp2p.peer.id import (
    ID,
)

logger = logging.getLogger("libp2p.relay.circuit_v2.nat")

# Timeout for reachability checks
REACHABILITY_TIMEOUT = 10  # seconds

# Define private IP ranges
PRIVATE_IP_RANGES = [
    ("10.0.0.0", "10.255.255.255"),  # Class A private network: 10.0.0.0/8
    ("172.16.0.0", "172.31.255.255"),  # Class B private network: 172.16.0.0/12
    ("192.168.0.0", "192.168.255.255"),  # Class C private network: 192.168.0.0/16
]

# Link-local address range: 169.254.0.0/16
LINK_LOCAL_RANGE = ("169.254.0.0", "169.254.255.255")

# Loopback address range: 127.0.0.0/8
LOOPBACK_RANGE = ("127.0.0.0", "127.255.255.255")


def ip_to_int(ip: str) -> int:
    """
    Convert an IP address to an integer.

    Parameters
    ----------
    ip : str
        IP address to convert

    Returns
    -------
    int
        Integer representation of the IP

    """
    try:
        return int(ipaddress.IPv4Address(ip))
    except ipaddress.AddressValueError:
        # Handle IPv6 addresses
        return int(ipaddress.IPv6Address(ip))


def is_ip_in_range(ip: str, start_range: str, end_range: str) -> bool:
    """
    Check if an IP address is within a range.

    Parameters
    ----------
    ip : str
        IP address to check
    start_range : str
        Start of the range
    end_range : str
        End of the range

    Returns
    -------
    bool
        True if the IP is in the range

    """
    try:
        ip_int = ip_to_int(ip)
        start_int = ip_to_int(start_range)
        end_int = ip_to_int(end_range)
        return start_int <= ip_int <= end_int
    except Exception:
        return False


def is_private_ip(ip: str) -> bool:
    """
    Check if an IP address is private.

    Parameters
    ----------
    ip : str
        IP address to check

    Returns
    -------
    bool
        True if IP is private

    """
    for start_range, end_range in PRIVATE_IP_RANGES:
        if is_ip_in_range(ip, start_range, end_range):
            return True

    # Check for link-local addresses
    if is_ip_in_range(ip, *LINK_LOCAL_RANGE):
        return True

    # Check for loopback addresses
    if is_ip_in_range(ip, *LOOPBACK_RANGE):
        return True

    return False


def extract_ip_from_multiaddr(addr: Multiaddr) -> str | None:
    """
    Extract the IP address from a multiaddr.

    Parameters
    ----------
    addr : Multiaddr
        Multiaddr to extract from

    Returns
    -------
    Optional[str]
        IP address or None if not found

    """
    # Convert to string representation
    addr_str = str(addr)

    # Look for IPv4 address
    ipv4_start = addr_str.find("/ip4/")
    if ipv4_start != -1:
        # Extract the IPv4 address
        ipv4_end = addr_str.find("/", ipv4_start + 5)
        if ipv4_end != -1:
            return addr_str[ipv4_start + 5 : ipv4_end]

    # Look for IPv6 address
    ipv6_start = addr_str.find("/ip6/")
    if ipv6_start != -1:
        # Extract the IPv6 address
        ipv6_end = addr_str.find("/", ipv6_start + 5)
        if ipv6_end != -1:
            return addr_str[ipv6_start + 5 : ipv6_end]

    return None


class ReachabilityChecker:
    """
    Utility class for checking peer reachability.

    This class assesses whether a peer's addresses are likely
    to be directly reachable or behind NAT.
    """

    def __init__(self, host: IHost):
        """
        Initialize the reachability checker.

        Parameters
        ----------
        host : IHost
            The libp2p host

        """
        self.host = host
        self._peer_reachability: dict[ID, bool] = {}
        self._known_public_peers: set[ID] = set()

    def is_addr_public(self, addr: Multiaddr) -> bool:
        """
        Check if an address is likely to be publicly reachable.

        Parameters
        ----------
        addr : Multiaddr
            The multiaddr to check

        Returns
        -------
        bool
            True if address is likely public

        """
        # Extract the IP address
        ip = extract_ip_from_multiaddr(addr)
        if not ip:
            return False

        # Check if it's a private IP
        return not is_private_ip(ip)

    def get_public_addrs(self, addrs: list[Multiaddr]) -> list[Multiaddr]:
        """
        Filter a list of addresses to only include likely public ones.

        Parameters
        ----------
        addrs : List[Multiaddr]
            List of addresses to filter

        Returns
        -------
        List[Multiaddr]
            List of likely public addresses

        """
        return [addr for addr in addrs if self.is_addr_public(addr)]

    async def check_peer_reachability(self, peer_id: ID) -> bool:
        """
        Check if a peer is directly reachable.

        Parameters
        ----------
        peer_id : ID
            The peer ID to check

        Returns
        -------
        bool
            True if peer is likely directly reachable

        """
        # Check if we already know
        if peer_id in self._peer_reachability:
            return self._peer_reachability[peer_id]

        # Check if the peer is connected
        network = self.host.get_network()
        connections: INetConn | list[INetConn] | None = network.connections.get(peer_id)
        if not connections:
            # Not connected, can't determine reachability
            return False

        # Check if any connection is direct (not relayed)
        if isinstance(connections, list):
            for conn in connections:
                # Get the transport addresses
                addrs = conn.get_transport_addresses()

                # If any address doesn't start with /p2p-circuit,
                # it's a direct connection
                if any(not str(addr).startswith("/p2p-circuit") for addr in addrs):
                    self._peer_reachability[peer_id] = True
                    return True
        else:
            # Handle single connection case
            addrs = connections.get_transport_addresses()
            if any(not str(addr).startswith("/p2p-circuit") for addr in addrs):
                self._peer_reachability[peer_id] = True
                return True

        # Get the peer's addresses from peerstore
        try:
            addrs = self.host.get_peerstore().addrs(peer_id)
            # Check if peer has any public addresses
            public_addrs = self.get_public_addrs(addrs)
            if public_addrs:
                self._peer_reachability[peer_id] = True
                return True
        except Exception as e:
            logger.debug("Error getting peer addresses: %s", str(e))

        # Default to not directly reachable
        self._peer_reachability[peer_id] = False
        return False

    async def check_self_reachability(self) -> tuple[bool, list[Multiaddr]]:
        """
        Check if this host is likely directly reachable.

        Returns
        -------
        Tuple[bool, List[Multiaddr]]
            Tuple of (is_reachable, public_addresses)

        """
        # Get all host addresses
        addrs = self.host.get_addrs()

        # Filter for public addresses
        public_addrs = self.get_public_addrs(addrs)

        # If we have public addresses, assume we're reachable
        # This is a simplified assumption - real reachability would need
        # external checking
        is_reachable = len(public_addrs) > 0

        return is_reachable, public_addrs

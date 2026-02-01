"""
Connection gating implementation for IP allow/deny lists.

This module provides connection filtering based on IP allow and deny lists,
implementing go-libp2p style ConnectionGater functionality.

Reference: https://pkg.go.dev/github.com/libp2p/go-libp2p/core/connmgr#ConnectionGater
"""

import ipaddress
import logging
import socket

from multiaddr import Multiaddr
import trio

logger = logging.getLogger("libp2p.network.connection_gate")


async def extract_ip_from_multiaddr(addr: Multiaddr) -> list[str]:
    """
    Extract IP addresses from a multiaddr.

    Handles both direct IP addresses (ip4, ip6) and DNS resolution
    (dns4, dns6, dnsaddr). Returns a list of IP addresses since DNS
    can resolve to multiple IPs.

    Parameters
    ----------
    addr : Multiaddr
        Multiaddr to extract IPs from

    Returns
    -------
    List[str]
        List of IP addresses. Empty list if no IPs found or resolution fails.

    Examples
    --------
    >>> await extract_ip_from_multiaddr(Multiaddr("/ip4/192.168.1.1/tcp/4001"))
    ['192.168.1.1']
    >>> await extract_ip_from_multiaddr(Multiaddr("/dns4/localhost/tcp/4001"))
    ['127.0.0.1']

    """
    from multiaddr.exceptions import ProtocolLookupError

    # Try direct IPv4 first
    try:
        ip = addr.value_for_protocol("ip4")
        return [ip]
    except ProtocolLookupError:
        pass

    # Try direct IPv6
    try:
        ip = addr.value_for_protocol("ip6")
        return [ip]
    except ProtocolLookupError:
        pass

    # Try DNS resolution for dns4, dns6, dnsaddr
    dns_protocols = [
        ("dns4", socket.AF_INET),
        ("dns6", socket.AF_INET6),
        ("dnsaddr", socket.AF_UNSPEC),  # Both IPv4 and IPv6
    ]

    for protocol, address_family in dns_protocols:
        try:
            hostname = addr.value_for_protocol(protocol)
            # Perform DNS resolution using trio
            try:
                addrinfo = await trio.socket.getaddrinfo(
                    hostname, None, family=address_family, type=socket.SOCK_STREAM
                )
                # Extract unique IP addresses
                ips: list[str] = list({str(info[4][0]) for info in addrinfo})
                logger.debug(f"Resolved {hostname} ({protocol}) to {ips}")
                return ips
            except (socket.gaierror, OSError) as e:
                logger.debug(f"Failed to resolve {protocol} hostname '{hostname}': {e}")
                return []
        except ProtocolLookupError:
            continue

    # No IP or resolvable DNS protocol found
    return []


class ConnectionGate:
    """
    Connection gate for IP allow/deny list filtering.

    Filters connections based on IP addresses and CIDR blocks.
    """

    def __init__(
        self,
        allow_list: list[str] | None = None,
        deny_list: list[str] | None = None,
        allow_private_addresses: bool = True,
    ):
        """
        Initialize connection gate.

        Parameters
        ----------
        allow_list : list[str] | None
            List of allowed IP addresses or CIDR blocks
        deny_list : list[str] | None
            List of denied IP addresses or CIDR blocks
        allow_private_addresses : bool
            Whether to allow private IP ranges (default: True)

        """
        self.allow_list: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self.deny_list: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        self.allow_private_addresses = allow_private_addresses

        # Parse allow list
        if allow_list:
            for entry in allow_list:
                try:
                    # Try parsing as network/CIDR
                    if "/" in entry:
                        network = ipaddress.ip_network(entry, strict=False)
                    else:
                        # Single IP address - convert to /32 or /128
                        ip = ipaddress.ip_address(entry)
                        prefixlen = ip.max_prefixlen
                        network = ipaddress.ip_network(
                            f"{ip}/{prefixlen}", strict=False
                        )
                    self.allow_list.append(network)
                except ValueError as e:
                    logger.warning(f"Invalid allow list entry '{entry}': {e}")

        # Parse deny list
        if deny_list:
            for entry in deny_list:
                try:
                    # Try parsing as network/CIDR
                    if "/" in entry:
                        network = ipaddress.ip_network(entry, strict=False)
                    else:
                        # Single IP address - convert to /32 or /128
                        ip = ipaddress.ip_address(entry)
                        prefixlen = ip.max_prefixlen
                        network = ipaddress.ip_network(
                            f"{ip}/{prefixlen}", strict=False
                        )
                    self.deny_list.append(network)
                except ValueError as e:
                    logger.warning(f"Invalid deny list entry '{entry}': {e}")

    def is_in_allow_list(self, remote_addr: Multiaddr) -> bool:
        """
        Check if connection is explicitly in allow list (sync, no DNS).

        This is a synchronous method that only checks direct IP addresses.
        For DNS resolution, use is_allowed() instead.

        Parameters
        ----------
        remote_addr : Multiaddr
            Remote address of the connection

        Returns
        -------
        bool
            True if IP is in allow list (and allow list exists)

        """
        if not self.allow_list:
            return False

        # Extract direct IP only (no DNS resolution)
        from multiaddr.exceptions import ProtocolLookupError

        ip_str: str | None = None
        try:
            ip_str = remote_addr.value_for_protocol("ip4")
        except ProtocolLookupError:
            try:
                ip_str = remote_addr.value_for_protocol("ip6")
            except ProtocolLookupError:
                return False

        if ip_str is None:
            return False

        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        for allow_net in self.allow_list:
            if ip in allow_net:
                return True

        return False

    async def is_allowed(self, remote_addr: Multiaddr) -> bool:
        """
        Check if a connection from the given address should be allowed.

        Handles both direct IP addresses and DNS resolution automatically.
        Non-IP multiaddrs (like /p2p-circuit) are allowed by default unless
        an allow list is configured.

        Parameters
        ----------
        remote_addr : Multiaddr
            Remote address of the connection

        Returns
        -------
        bool
            True if connection should be allowed, False otherwise

        """
        # Extract IP addresses from multiaddr (handles both direct IPs and DNS)
        ip_addresses = await extract_ip_from_multiaddr(remote_addr)

        if not ip_addresses:
            # No IP addresses found (e.g., /p2p-circuit addresses)
            # Allow by default unless an allow list is configured
            if not self.allow_list:
                logger.debug(
                    f"No IP addresses in multiaddr {remote_addr}, allowing by default"
                )
                return True
            else:
                logger.debug(
                    f"No IP addresses in multiaddr {remote_addr}, "
                    f"denying due to allow_list"
                )
                return False

        # Check if any of the resolved IPs is allowed
        for ip_str in ip_addresses:
            if self._check_ip_allowed(ip_str):
                return True

        # None of the IPs are allowed
        return False

    def _check_ip_allowed(self, ip_str: str) -> bool:
        """
        Check if a specific IP address should be allowed.

        Parameters
        ----------
        ip_str : str
            IP address to check

        Returns
        -------
        bool
            True if IP should be allowed, False otherwise

        """
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            logger.debug(f"Invalid IP address '{ip_str}'")
            return False

        # Check if IP is private and private addresses are not allowed
        if not self.allow_private_addresses and ip.is_private:
            logger.debug(
                f"Private IP address {ip_str} denied (private addresses not allowed)"
            )
            return False

        # Check deny list first (deny takes precedence)
        for deny_net in self.deny_list:
            if ip in deny_net:
                logger.debug(
                    f"Connection from {ip_str} denied - "
                    f"IP address in deny list ({deny_net})"
                )
                return False

        # Check allow list (if allow list exists, only allowed IPs are permitted)
        if self.allow_list:
            for allow_net in self.allow_list:
                if ip in allow_net:
                    logger.debug(
                        f"Connection from {ip_str} allowed - "
                        f"IP address in allow list ({allow_net})"
                    )
                    return True

            # Allow list exists but IP not in it
            logger.debug(
                f"Connection from {ip_str} denied - IP address not in allow list"
            )
            return False

        # No allow list - allow all (except deny list which was already checked)
        return True

    def add_to_allow_list(self, entry: str) -> None:
        """
        Add an entry to the allow list.

        Parameters
        ----------
        entry : str
            IP address or CIDR block to add

        """
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
            else:
                ip = ipaddress.ip_address(entry)
                network = ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False)
            self.allow_list.append(network)
            logger.debug(f"Added {entry} to allow list")
        except ValueError as e:
            logger.warning(f"Invalid allow list entry '{entry}': {e}")

    def remove_from_allow_list(self, entry: str) -> None:
        """
        Remove an entry from the allow list.

        Parameters
        ----------
        entry : str
            IP address or CIDR block to remove

        """
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
            else:
                ip = ipaddress.ip_address(entry)
                network = ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False)

            self.allow_list = [n for n in self.allow_list if n != network]
            logger.debug(f"Removed {entry} from allow list")
        except ValueError as e:
            logger.warning(f"Invalid allow list entry '{entry}': {e}")

    def add_to_deny_list(self, entry: str) -> None:
        """
        Add an entry to the deny list.

        Parameters
        ----------
        entry : str
            IP address or CIDR block to add

        """
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
            else:
                ip = ipaddress.ip_address(entry)
                network = ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False)
            self.deny_list.append(network)
            logger.debug(f"Added {entry} to deny list")
        except ValueError as e:
            logger.warning(f"Invalid deny list entry '{entry}': {e}")

    def remove_from_deny_list(self, entry: str) -> None:
        """
        Remove an entry from the deny list.

        Parameters
        ----------
        entry : str
            IP address or CIDR block to remove

        """
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
            else:
                ip = ipaddress.ip_address(entry)
                network = ipaddress.ip_network(f"{ip}/{ip.max_prefixlen}", strict=False)

            try:
                self.deny_list.remove(network)
                logger.debug(f"Removed {entry} from deny list")
            except ValueError:
                # Not present, so nothing to remove
                pass
        except ValueError as e:
            logger.warning(f"Invalid deny list entry '{entry}': {e}")

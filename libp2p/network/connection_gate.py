"""
Connection gating implementation for IP allow/deny lists.

This module provides connection filtering based on IP allow and deny lists,
matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/index.ts
"""

import ipaddress
import logging

from multiaddr import Multiaddr

from libp2p.network.address_manager import extract_ip_from_multiaddr

logger = logging.getLogger("libp2p.network.connection_gate")


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
        Check if connection is explicitly in allow list.

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

        ip_str = extract_ip_from_multiaddr(remote_addr)
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

    def is_allowed(self, remote_addr: Multiaddr) -> bool:
        """
        Check if a connection from the given address should be allowed.

        Parameters
        ----------
        remote_addr : Multiaddr
            Remote address of the connection

        Returns
        -------
        bool
            True if connection should be allowed, False otherwise

        """
        # Extract IP address from multiaddr
        ip_str = extract_ip_from_multiaddr(remote_addr)
        if ip_str is None:
            # No IP address found - default to deny for safety
            logger.debug(f"No IP address found in multiaddr {remote_addr}")
            return False

        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            logger.debug(f"Invalid IP address '{ip_str}' from multiaddr {remote_addr}")
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

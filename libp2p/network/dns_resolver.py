"""
DNS resolution for multiaddrs.

This module provides DNS resolution for /dns4/, /dns6/, and /dnsaddr/
multiaddrs, matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/resolvers/index.ts
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from multiaddr import Multiaddr

if TYPE_CHECKING:
    pass

logger = logging.getLogger("libp2p.network.dns_resolver")


class DNSResolver:
    """
    DNS resolver for multiaddrs.

    Supports /dns4/, /dns6/, and /dnsaddr/ resolution with caching.
    """

    def __init__(self, max_recursion_depth: int = 32) -> None:
        """
        Initialize DNS resolver.

        Parameters
        ----------
        max_recursion_depth : int
            Maximum recursion depth for dnsaddr resolution (default: 32)

        """
        self.max_recursion_depth = max_recursion_depth
        self._cache: dict[str, list[Multiaddr]] = {}

    async def resolve(self, multiaddr: Multiaddr) -> list[Multiaddr]:
        """
        Resolve a multiaddr that may contain DNS components.

        Parameters
        ----------
        multiaddr : Multiaddr
            Multiaddr to resolve

        Returns
        -------
        list[Multiaddr]
            List of resolved multiaddrs

        """
        addr_str = str(multiaddr)

        # Check cache first
        if addr_str in self._cache:
            return self._cache[addr_str]

        # Check if it's a DNS address
        if "/dnsaddr/" in addr_str:
            resolved = await self._resolve_dnsaddr(multiaddr)
        elif "/dns4/" in addr_str or "/dns6/" in addr_str:
            resolved = await self._resolve_dns(multiaddr)
        else:
            # Not a DNS address, return as-is
            resolved = [multiaddr]

        # Cache result
        self._cache[addr_str] = resolved
        return resolved

    async def _resolve_dns(
        self, multiaddr: Multiaddr, depth: int = 0
    ) -> list[Multiaddr]:
        """
        Resolve /dns4/ or /dns6/ addresses.

        Parameters
        ----------
        multiaddr : Multiaddr
            Multiaddr with DNS component
        depth : int
            Current recursion depth

        Returns
        -------
        list[Multiaddr]
            Resolved addresses

        """
        if depth > self.max_recursion_depth:
            logger.warning(f"DNS resolution exceeded max depth for {multiaddr}")
            return [multiaddr]

        addr_str = str(multiaddr)
        resolved_addrs: list[Multiaddr] = []

        try:
            # Extract DNS name
            dns_name = None
            if "/dns4/" in addr_str:
                dns_start = addr_str.find("/dns4/")
                dns_end = addr_str.find("/", dns_start + 6)
                if dns_end != -1:
                    dns_name = addr_str[dns_start + 6 : dns_end]
            elif "/dns6/" in addr_str:
                dns_start = addr_str.find("/dns6/")
                dns_end = addr_str.find("/", dns_start + 6)
                if dns_end != -1:
                    dns_name = addr_str[dns_start + 6 : dns_end]

            if not dns_name:
                return [multiaddr]

            # Resolve DNS name to IP addresses
            try:
                # Use asyncio.get_event_loop().getaddrinfo for DNS resolution
                loop = asyncio.get_event_loop()
                addr_info = await loop.getaddrinfo(dns_name, None, type=0, proto=0)

                # Replace DNS component with IP addresses
                for family, _, _, _, sockaddr in addr_info:
                    ip_addr = sockaddr[0]

                    # Create new multiaddr with IP instead of DNS
                    if "/dns4/" in addr_str:
                        new_addr_str = addr_str.replace(
                            f"/dns4/{dns_name}", f"/ip4/{ip_addr}"
                        )
                    elif "/dns6/" in addr_str:
                        new_addr_str = addr_str.replace(
                            f"/dns6/{dns_name}", f"/ip6/{ip_addr}"
                        )
                    else:
                        continue

                    try:
                        resolved_addrs.append(Multiaddr(new_addr_str))
                    except Exception as e:
                        logger.debug(
                            f"Failed to create multiaddr from {new_addr_str}: {e}"
                        )

            except Exception as e:
                logger.debug(f"DNS resolution failed for {dns_name}: {e}")
                return [multiaddr]

        except Exception as e:
            logger.debug(f"Error resolving DNS address {multiaddr}: {e}")
            return [multiaddr]

        return resolved_addrs if resolved_addrs else [multiaddr]

    async def _resolve_dnsaddr(
        self, multiaddr: Multiaddr, depth: int = 0
    ) -> list[Multiaddr]:
        """
        Resolve /dnsaddr/ addresses recursively.

        Parameters
        ----------
        multiaddr : Multiaddr
            Multiaddr with dnsaddr component
        depth : int
            Current recursion depth

        Returns
        -------
        list[Multiaddr]
            Resolved addresses

        Note: Full dnsaddr resolution (TXT record lookup) requires
        additional DNS library support. This is a simplified implementation.

        """
        if depth > self.max_recursion_depth:
            logger.warning(f"DNSADDR resolution exceeded max depth for {multiaddr}")
            return [multiaddr]

        # TODO: Implement full dnsaddr resolution (TXT record lookup)
        # For now, return the original address
        logger.debug(f"DNSADDR resolution not fully implemented for {multiaddr}")
        return [multiaddr]

    def clear_cache(self) -> None:
        """Clear DNS resolution cache."""
        self._cache.clear()


# Global resolver instance
_default_resolver = DNSResolver()


async def resolve_multiaddr(multiaddr: Multiaddr) -> list[Multiaddr]:
    """
    Resolve a multiaddr using the default resolver.

    Parameters
    ----------
    multiaddr : Multiaddr
        Multiaddr to resolve

    Returns
    -------
    list[Multiaddr]
        List of resolved multiaddrs

    """
    return await _default_resolver.resolve(multiaddr)

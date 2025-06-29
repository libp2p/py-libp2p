"""Utility functions for bootstrap discovery."""

import logging

from multiaddr import Multiaddr

from libp2p.peer.peerinfo import InvalidAddrError, PeerInfo, info_from_p2p_addr

logger = logging.getLogger("libp2p.discovery.bootstrap.utils")


def validate_bootstrap_addresses(addrs: list[str]) -> list[str]:
    """
    Validate and filter bootstrap addresses.

    :param addrs: List of bootstrap address strings
    :return: List of valid bootstrap addresses
    """
    valid_addrs = []

    for addr_str in addrs:
        try:
            # Try to parse as multiaddr
            multiaddr = Multiaddr(addr_str)

            # Try to extract peer info (this validates the p2p component)
            info_from_p2p_addr(multiaddr)

            valid_addrs.append(addr_str)
            logger.debug(f"Valid bootstrap address: {addr_str}")

        except (InvalidAddrError, ValueError, Exception) as e:
            logger.warning(f"Invalid bootstrap address '{addr_str}': {e}")
            continue

    return valid_addrs


def parse_bootstrap_peer_info(addr_str: str) -> PeerInfo | None:
    """
    Parse bootstrap address string into PeerInfo.

    :param addr_str: Bootstrap address string
    :return: PeerInfo object or None if parsing fails
    """
    try:
        multiaddr = Multiaddr(addr_str)
        return info_from_p2p_addr(multiaddr)
    except Exception as e:
        logger.error(f"Failed to parse bootstrap address '{addr_str}': {e}")
        return None

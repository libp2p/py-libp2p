"""
Multiaddr utilities for IP address extraction and detection.

This module provides helper functions for working with multiaddrs that contain
either IPv4 or IPv6 addresses, ensuring consistent handling across all transports.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import TYPE_CHECKING

from multiaddr import Multiaddr

if TYPE_CHECKING:
    import trio.socket


def extract_ip_from_multiaddr(maddr: Multiaddr) -> str | None:
    """
    Extract IP address (IPv4 or IPv6) from a multiaddr.

    Tries IPv4 first for backward compatibility, then falls back to IPv6.

    :param maddr: Multiaddr to extract IP from
    :return: IP address string or None if not found
    """
    # Try IPv4 first (for backward compatibility)
    try:
        ip4 = maddr.value_for_protocol("ip4")
        if ip4:
            return ip4
    except Exception:
        pass

    # Try IPv6
    try:
        ip6 = maddr.value_for_protocol("ip6")
        if ip6:
            return ip6
    except Exception:
        pass

    return None


def get_ip_protocol_from_multiaddr(maddr: Multiaddr) -> str | None:
    """
    Get the IP protocol name (ip4 or ip6) from a multiaddr.

    :param maddr: Multiaddr to check
    :return: Protocol name ("ip4" or "ip6") or None if neither found
    """
    try:
        maddr.value_for_protocol("ip4")
        return "ip4"
    except Exception:
        try:
            maddr.value_for_protocol("ip6")
            return "ip6"
        except Exception:
            return None


def extract_ip_and_protocol(maddr: Multiaddr) -> tuple[str | None, str | None]:
    """
    Extract both IP address and protocol type from a multiaddr.

    :param maddr: Multiaddr to extract from
    :return: Tuple of (ip_address, protocol_name) e.g., ("127.0.0.1", "ip4")
             or ("::1", "ip6"). Returns (None, None) if not found.
    """
    # Try IPv4 first
    try:
        ip4 = maddr.value_for_protocol("ip4")
        if ip4:
            return ip4, "ip4"
    except Exception:
        pass

    # Try IPv6
    try:
        ip6 = maddr.value_for_protocol("ip6")
        if ip6:
            return ip6, "ip6"
    except Exception:
        pass

    return None, None


def get_ip_protocol_from_address(addr: str) -> str:
    """
    Detect if an IP address string is IPv4 or IPv6.

    Uses the presence of colons as the primary indicator (IPv6 addresses
    contain colons, IPv4 addresses do not).

    :param addr: IP address string
    :return: "ip6" if address contains colons, "ip4" otherwise
    """
    if ":" in addr:
        return "ip6"
    return "ip4"


def is_ipv6_address(addr: str) -> bool:
    """
    Check if an address string represents an IPv6 address.

    :param addr: IP address string to check
    :return: True if IPv6, False otherwise
    """
    return ":" in addr


def validate_ip_address(addr: str) -> tuple[str, int]:
    """
    Validate an IP address string and return its version.

    :param addr: IP address string to validate
    :return: Tuple of (validated_address, version) where version is 4 or 6
    :raises ValueError: If address is not a valid IP address
    """
    ip = ipaddress.ip_address(addr)
    return str(ip), ip.version


def multiaddr_from_socket_address(
    host: str, port: int, transport_protocol: str = "tcp"
) -> Multiaddr:
    """
    Create a multiaddr from a socket address (host, port).

    Automatically detects whether the host is IPv4 or IPv6.

    :param host: IP address string
    :param port: Port number
    :param transport_protocol: Transport protocol (default: "tcp")
    :return: Multiaddr with appropriate IP protocol
    """
    ip_protocol = get_ip_protocol_from_address(host)
    return Multiaddr(f"/{ip_protocol}/{host}/{transport_protocol}/{port}")


def multiaddr_from_trio_socket(
    sock: "trio.socket.SocketType", transport_protocol: str = "tcp"
) -> Multiaddr:
    """
    Create a multiaddr from a trio socket.

    Detects the socket family (AF_INET vs AF_INET6) and creates the
    appropriate multiaddr.

    :param sock: Trio socket to get address from
    :param transport_protocol: Transport protocol (default: "tcp")
    :return: Multiaddr with appropriate IP protocol
    """
    sockname = sock.getsockname()
    host = sockname[0]
    port = sockname[1]

    # Check socket family for accurate detection
    if sock.family == socket.AF_INET6:
        return Multiaddr(f"/ip6/{host}/{transport_protocol}/{port}")
    elif sock.family == socket.AF_INET:
        return Multiaddr(f"/ip4/{host}/{transport_protocol}/{port}")
    else:
        # Fallback: detect from address string
        ip_protocol = get_ip_protocol_from_address(host)
        return Multiaddr(f"/{ip_protocol}/{host}/{transport_protocol}/{port}")


__all__ = [
    "extract_ip_from_multiaddr",
    "get_ip_protocol_from_multiaddr",
    "extract_ip_and_protocol",
    "get_ip_protocol_from_address",
    "is_ipv6_address",
    "validate_ip_address",
    "multiaddr_from_socket_address",
    "multiaddr_from_trio_socket",
]

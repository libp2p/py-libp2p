"""
Multiaddr utility functions for IPv4/IPv6 handling.

This module provides helper functions to extract IP addresses from multiaddrs
in a version-agnostic way, supporting both IPv4 and IPv6.
Uses py-multiaddr utilities (e.g. get_multiaddr_options) when available.
"""

import socket
from typing import Any

from multiaddr import Multiaddr
from multiaddr.utils import get_multiaddr_options


def join_multiaddrs(*addrs: str | bytes | Multiaddr) -> Multiaddr:
    """
    Concatenate multiple multiaddrs (Section 7.1).

    Uses Multiaddr.join() when available (py-multiaddr 0.1.1+), otherwise
    chains encapsulate() for compatibility with older versions.

    :param addrs: One or more multiaddr strings, bytes, or Multiaddr instances
    :return: Single Multiaddr combining all parts in order
    """
    if not addrs:
        return Multiaddr("")
    # Normalize to Multiaddr for fallback path
    normalized = [a if isinstance(a, Multiaddr) else Multiaddr(a) for a in addrs]
    join_method = getattr(Multiaddr, "join", None)
    if callable(join_method):
        return Multiaddr.join(*addrs)
    result = normalized[0]
    for a in normalized[1:]:
        result = result.encapsulate(a)
    return result


def extract_ip_from_multiaddr(maddr: Multiaddr) -> str | None:
    """
    Extract IP address (IPv4 or IPv6) from multiaddr using py-multiaddr utilities.

    Prefers get_multiaddr_options for consistent parsing; falls back to
    value_for_protocol for ip4/ip6 when options do not provide a host.

    :param maddr: Multiaddr to extract from
    :return: IP address string or None if not found
    """
    try:
        options = get_multiaddr_options(maddr)
        if options:
            host = options.get("host")
            if host:
                return host
    except Exception:
        pass

    try:
        ip4 = maddr.value_for_protocol("ip4")
        if ip4:
            return ip4
    except Exception:
        pass

    try:
        ip6 = maddr.value_for_protocol("ip6")
        if ip6:
            return ip6
    except Exception:
        pass

    return None


def get_protocol_layers(maddr: Multiaddr, maxsplit: int = -1) -> list[Multiaddr]:
    """
    Return protocol stack as per-layer multiaddrs (Section 3.2 multiaddr integration).

    Uses Multiaddr.split() for protocol stack analysis and debugging.

    :param maddr: Multiaddr to analyze
    :param maxsplit: Optional max number of splits (-1 for no limit)
    :return: List of Multiaddr, one per protocol layer
    """
    try:
        return list(maddr.split(maxsplit=maxsplit))
    except Exception:
        return [maddr]


def get_ip_protocol_from_multiaddr(maddr: Multiaddr) -> str | None:
    """
    Get the IP protocol name (ip4 or ip6) from multiaddr.

    :param maddr: Multiaddr to check
    :return: Protocol name ("ip4" or "ip6") or None
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


def multiaddr_from_socket(socket_obj: socket.socket | Any) -> Multiaddr:
    """
    Create multiaddr from socket, detecting IPv4 or IPv6.

    :param socket_obj: Socket to get address from (socket.socket or trio.SocketType)
    :return: Multiaddr with appropriate IP protocol
    """
    sockname = socket_obj.getsockname()
    family = socket_obj.family

    if family == socket.AF_INET6:
        ip, port, flow_info, scope_id = sockname
        return Multiaddr(f"/ip6/{ip}/tcp/{port}")
    else:
        ip, port = sockname
        return Multiaddr(f"/ip4/{ip}/tcp/{port}")


__all__ = [
    "extract_ip_from_multiaddr",
    "get_ip_protocol_from_multiaddr",
    "get_protocol_layers",
    "join_multiaddrs",
    "multiaddr_from_socket",
]

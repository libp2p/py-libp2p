"""
Multiaddr utility functions for IPv4/IPv6 handling.

This module provides helper functions to extract IP addresses from multiaddrs
in a version-agnostic way, supporting both IPv4 and IPv6.
"""

import socket
from typing import Any

from multiaddr import Multiaddr


def extract_ip_from_multiaddr(maddr: Multiaddr) -> str | None:
    """
    Extract IP address (IPv4 or IPv6) from multiaddr.

    :param maddr: Multiaddr to extract from
    :return: IP address string or None if not found
    """
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


def extract_host_from_multiaddr(maddr: Multiaddr) -> str | None:
    """
    Extract host (IP or DNS name) from multiaddr.

    Tries ip4, ip6, dns, dns4, dns6 in order. Returns the first found value,
    or None if no host protocol is present. Handles ``ProtocolLookupError``
    gracefully for each protocol.

    :param maddr: Multiaddr to extract host from
    :return: Host string or None if not found
    """
    for protocol in ("ip4", "ip6", "dns", "dns4", "dns6"):
        try:
            value = maddr.value_for_protocol(protocol)
            if value:
                return value
        except Exception:
            continue
    return None


def format_host_for_url(host: str) -> str:
    """
    Format host for use in URLs.

    IPv6 addresses (detected by presence of ``:``) are wrapped in square
    brackets per `RFC 3986 <https://www.rfc-editor.org/rfc/rfc3986>`_.

    Examples::

        >>> format_host_for_url("127.0.0.1")
        '127.0.0.1'
        >>> format_host_for_url("::1")
        '[::1]'
        >>> format_host_for_url("example.com")
        'example.com'

    :param host: Hostname or IP address string
    :return: Host formatted for URL inclusion
    """
    if ":" in host:
        return f"[{host}]"
    return host


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
    "extract_host_from_multiaddr",
    "extract_ip_from_multiaddr",
    "format_host_for_url",
    "get_ip_protocol_from_multiaddr",
    "multiaddr_from_socket",
]

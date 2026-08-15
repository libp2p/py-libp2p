from __future__ import annotations

import functools
import ipaddress
import logging
import socket

from multiaddr import Multiaddr
from multiaddr.utils import get_network_addrs, get_thin_waist_addresses

logger = logging.getLogger(__name__)


def _safe_get_network_addrs(ip_version: int) -> list[str]:
    """
    Internal safe wrapper. Returns a list of IP addresses for the requested IP version.

    :param ip_version: 4 or 6
    """
    try:
        return get_network_addrs(ip_version) or []
    except Exception:  # pragma: no cover - defensive
        # Fallback behavior (very conservative)
        if ip_version == 4:
            return ["127.0.0.1"]
        if ip_version == 6:
            return ["::1"]
        return []


def find_free_port(ip_version: int = 4) -> int:
    """
    Find a free port on localhost.

    :param ip_version: IP version (4 for IPv4, 6 for IPv6)
    :return: Available port number
    """
    family = socket.AF_INET6 if ip_version == 6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.bind(("", 0))  # Bind to a free port provided by the OS
        return s.getsockname()[1]


def _validate_ipv4_address(address: str) -> str:
    """
    Validate that a given address is a valid IPv4 address.

    Args:
        address: The IP address string to validate

    Returns:
        The validated IPv4 address, or "127.0.0.1" if invalid

    """
    try:
        ipaddress.IPv4Address(address)
        return address
    except (ipaddress.AddressValueError, ValueError):
        return "127.0.0.1"


def _validate_ipv6_address(address: str) -> str:
    """
    Validate that a given address is a valid IPv6 address.

    Args:
        address: The IP address string to validate

    Returns:
        The validated IPv6 address, or "::1" if invalid

    """
    try:
        ipaddress.IPv6Address(address)
        return address
    except (ipaddress.AddressValueError, ValueError):
        return "::1"


def _safe_expand(addr: Multiaddr, port: int | None = None) -> list[Multiaddr]:
    """
    Internal safe expansion wrapper. Returns a list of Multiaddr objects.
    """
    try:
        if port is not None:
            return get_thin_waist_addresses(addr, port=port) or []
        return get_thin_waist_addresses(addr) or []
    except Exception:  # pragma: no cover - defensive
        return [addr]


@functools.lru_cache(maxsize=1)
def is_ipv6_available() -> bool:
    """
    Probe once at startup whether the OS has usable IPv6.
    Caches the result for the lifetime of the process.

    NOTE: this only proves the OS *speaks* IPv6 (loopback binding).  Hosts
    without a public IPv6 address still pass this check but cannot reach
    public IPv6 peers; use :func:`has_public_ipv6` for dial filtering.
    """
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


@functools.lru_cache(maxsize=1)
def has_public_ipv6() -> bool:
    """
    Return True if the host has a usable non-loopback IPv6 interface.

    Some hosts (e.g. EC2 instances without an IPv6 subnet) have IPv6 enabled
    on loopback (``::1``) but no IPv6 routing, so every dial to a public
    IPv6 peer fails with ``Network is unreachable``.  This probe requires at
    least one non-loopback IPv6 address before reporting IPv6 as usable for
    dialing.

    On Linux it reads the kernel's IPv6 address table
    (``/proc/net/if_inet6``); on other platforms it falls back to the
    loopback probe from :func:`is_ipv6_available`.
    """
    try:
        # /proc/net/if_inet6 lines:
        #   address(32 hex) index prefixlen scope flags ifname
        # The scope column (4th) discriminates address types: 00 = global,
        # 10 = host (loopback), 20 = link-local.  Only a global-scope,
        # non-loopback address implies the host can actually reach public
        # IPv6 peers; link-local/ULA/Docker-bridge IPv6 does not.
        with open("/proc/net/if_inet6", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 6 and parts[3] == "00" and parts[5] != "lo":
                    return True
        return False
    except OSError:
        # Non-Linux (e.g. macOS) or unreadable: fall back to the loopback
        # probe (the old behavior).
        return is_ipv6_available()


def is_relay_address(addr: Multiaddr) -> bool:
    """
    Return True if the multiaddr traverses a relay (``/p2p-circuit``).

    Relay paths are only usable when a relay client is configured; this
    node does not use one, so dialing them is pure waste — the QUIC
    transport cannot even derive a peer id from a ``/p2p-circuit`` address
    and fails every attempt.  Parsing is done defensively so malformed
    multiaddrs never raise.
    """
    try:
        return "p2p-circuit" in {p.name for p in addr.protocols()}
    except Exception:
        return False


def get_available_interfaces(port: int, protocol: str = "tcp") -> list[Multiaddr]:
    """
    Discover available network interfaces (IPv4 + IPv6 if supported) for binding.

    :param port: Port number to bind to.
    :param protocol: Transport protocol (e.g., "tcp" or "udp").
    :return: List of Multiaddr objects representing candidate interface addresses.
    """
    addrs: list[Multiaddr] = []

    # IPv4 enumeration
    seen_v4: set[str] = set()

    for ip in _safe_get_network_addrs(4):
        if ip not in seen_v4:  # Avoid duplicates
            seen_v4.add(ip)
            addrs.append(Multiaddr(f"/ip4/{ip}/{protocol}/{port}"))

    # Ensure IPv4 loopback is always included when IPv4 interfaces are discovered
    if seen_v4 and "127.0.0.1" not in seen_v4:
        addrs.append(Multiaddr(f"/ip4/127.0.0.1/{protocol}/{port}"))

    if not is_ipv6_available():
        logger.debug("IPv6 not available on this host — skipping ip6 listen addrs")
        return addrs

    seen_v6: set[str] = set()
    for ip in _safe_get_network_addrs(6):
        if ip not in seen_v6:  # Avoid duplicates
            seen_v6.add(ip)
            addrs.append(Multiaddr(f"/ip6/{ip}/{protocol}/{port}"))

    # Always include IPv6 loopback for testing purposes when IPv6 is available
    # This ensures IPv6 functionality can be tested even without global IPv6 addresses
    if "::1" not in seen_v6:
        addrs.append(Multiaddr(f"/ip6/::1/{protocol}/{port}"))

    # Fallback if nothing discovered
    if not addrs:
        addrs.append(Multiaddr(f"/ip4/127.0.0.1/{protocol}/{port}"))

    return addrs


def expand_wildcard_address(
    addr: Multiaddr, port: int | None = None
) -> list[Multiaddr]:
    """
    Expand a wildcard (e.g. /ip4/0.0.0.0/tcp/0) into all concrete interfaces.

    :param addr: Multiaddr to expand.
    :param port: Optional override for port selection.
    :return: List of concrete Multiaddr instances.
    """
    expanded = _safe_expand(addr, port=port)
    if not expanded:  # Safety fallback
        return [addr]
    return expanded


def get_wildcard_address(
    port: int, protocol: str = "tcp", ip_version: int = 4
) -> Multiaddr:
    """
    Get wildcard address (0.0.0.0 or ::) when explicitly needed.

    This function provides access to wildcard binding as a feature when
    explicitly required, preserving the ability to bind to all interfaces.

    :param port: Port number.
    :param protocol: Transport protocol.
    :param ip_version: IP version (4 for 0.0.0.0, 6 for ::).
    :return: A Multiaddr with wildcard binding (0.0.0.0 or ::).
    """
    if ip_version == 6:
        return Multiaddr(f"/ip6/::/{protocol}/{port}")
    else:
        return Multiaddr(f"/ip4/0.0.0.0/{protocol}/{port}")


def get_optimal_binding_address(port: int, protocol: str = "tcp") -> Multiaddr:
    """
    Choose an optimal address for an example to bind to:
    - Prefer non-loopback IPv6
    - Then non-loopback IPv4
    - Then loopback IPv6
    - Then loopback IPv4
    - Fallback to wildcard IPv4

    :param port: Port number.
    :param protocol: Transport protocol.
    :return: A single Multiaddr chosen heuristically.
    """
    candidates = get_available_interfaces(port, protocol)

    def is_non_loopback(ma: Multiaddr) -> bool:
        s = str(ma)
        return not ("/ip4/127." in s or "/ip6/::1" in s)

    for c in candidates:
        if "/ip6/" in str(c) and is_non_loopback(c):
            return c
    for c in candidates:
        if "/ip4/" in str(c) and is_non_loopback(c):
            return c
    for c in candidates:
        if "/ip6/::1" in str(c):
            return c
    for c in candidates:
        if "/ip4/127." in str(c):
            return c

    # As a final fallback, produce a loopback address
    return Multiaddr(f"/ip4/127.0.0.1/{protocol}/{port}")


__all__ = [
    "get_available_interfaces",
    "get_optimal_binding_address",
    "get_wildcard_address",
    "expand_wildcard_address",
    "find_free_port",
    "has_public_ipv6",
    "is_relay_address",
]

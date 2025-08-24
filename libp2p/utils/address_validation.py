from __future__ import annotations

from multiaddr import Multiaddr

try:
    from multiaddr.utils import (  # type: ignore
        get_network_addrs,
        get_thin_waist_addresses,
    )

    _HAS_THIN_WAIST = True
except ImportError:  # pragma: no cover - only executed in older environments
    _HAS_THIN_WAIST = False
    get_thin_waist_addresses = None  # type: ignore
    get_network_addrs = None  # type: ignore


def _safe_get_network_addrs(ip_version: int) -> list[str]:
    """
    Internal safe wrapper. Returns a list of IP addresses for the requested IP version.
    Falls back to minimal defaults when Thin Waist helpers are missing.

    :param ip_version: 4 or 6
    """
    if _HAS_THIN_WAIST and get_network_addrs:
        try:
            return get_network_addrs(ip_version) or []
        except Exception:  # pragma: no cover - defensive
            return []
    # Fallback behavior (very conservative)
    if ip_version == 4:
        return ["127.0.0.1"]
    if ip_version == 6:
        return ["::1"]
    return []


def _safe_expand(addr: Multiaddr, port: int | None = None) -> list[Multiaddr]:
    """
    Internal safe expansion wrapper. Returns a list of Multiaddr objects.
    If Thin Waist isn't available, returns [addr] (identity).
    """
    if _HAS_THIN_WAIST and get_thin_waist_addresses:
        try:
            if port is not None:
                return get_thin_waist_addresses(addr, port=port) or []
            return get_thin_waist_addresses(addr) or []
        except Exception:  # pragma: no cover - defensive
            return [addr]
    return [addr]


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
        seen_v4.add(ip)
        addrs.append(Multiaddr(f"/ip4/{ip}/{protocol}/{port}"))

    # Ensure IPv4 loopback is always included when IPv4 interfaces are discovered
    if seen_v4 and "127.0.0.1" not in seen_v4:
        addrs.append(Multiaddr(f"/ip4/127.0.0.1/{protocol}/{port}"))

    # TODO: IPv6 support temporarily disabled due to libp2p handshake issues
    # IPv6 connections fail during protocol negotiation (SecurityUpgradeFailure)
    # Re-enable IPv6 support once the following issues are resolved:
    # - libp2p security handshake over IPv6
    # - multiselect protocol over IPv6
    # - connection establishment over IPv6
    #
    # seen_v6: set[str] = set()
    # for ip in _safe_get_network_addrs(6):
    #     seen_v6.add(ip)
    #     addrs.append(Multiaddr(f"/ip6/{ip}/{protocol}/{port}"))
    #
    # # Always include IPv6 loopback for testing purposes when IPv6 is available
    # # This ensures IPv6 functionality can be tested even without global IPv6 addresses
    # if "::1" not in seen_v6:
    #     addrs.append(Multiaddr(f"/ip6/::1/{protocol}/{port}"))

    # Fallback if nothing discovered
    if not addrs:
        addrs.append(Multiaddr(f"/ip4/0.0.0.0/{protocol}/{port}"))

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


def get_optimal_binding_address(port: int, protocol: str = "tcp") -> Multiaddr:
    """
    Choose an optimal address for an example to bind to:
    - Prefer non-loopback IPv4
    - Then non-loopback IPv6
    - Fallback to loopback
    - Fallback to wildcard

    :param port: Port number.
    :param protocol: Transport protocol.
    :return: A single Multiaddr chosen heuristically.
    """
    candidates = get_available_interfaces(port, protocol)

    def is_non_loopback(ma: Multiaddr) -> bool:
        s = str(ma)
        return not ("/ip4/127." in s or "/ip6/::1" in s)

    for c in candidates:
        if "/ip4/" in str(c) and is_non_loopback(c):
            return c
    for c in candidates:
        if "/ip6/" in str(c) and is_non_loopback(c):
            return c
    for c in candidates:
        if "/ip4/127." in str(c) or "/ip6/::1" in str(c):
            return c

    # As a final fallback, produce a wildcard
    return Multiaddr(f"/ip4/0.0.0.0/{protocol}/{port}")


__all__ = [
    "get_available_interfaces",
    "get_optimal_binding_address",
    "expand_wildcard_address",
]

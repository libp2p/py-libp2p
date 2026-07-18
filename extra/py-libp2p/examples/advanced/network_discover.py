"""
Advanced demonstration of Thin Waist address handling.

Run:
    python -m examples.advanced.network_discovery
"""

from __future__ import annotations

from multiaddr import Multiaddr

try:
    from libp2p.utils.address_validation import (
        expand_wildcard_address,
        get_available_interfaces,
        get_optimal_binding_address,
        get_wildcard_address,
    )
except ImportError:
    # Fallbacks if utilities are missing - use minimal network discovery
    import socket

    def get_available_interfaces(port: int, protocol: str = "tcp"):
        # Try to get local network interfaces, fallback to loopback
        addrs = []
        try:
            # Get hostname IP (better than hardcoded localhost)
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip != "127.0.0.1":
                addrs.append(Multiaddr(f"/ip4/{local_ip}/{protocol}/{port}"))
        except Exception:
            pass
        # Always include loopback as fallback
        addrs.append(Multiaddr(f"/ip4/127.0.0.1/{protocol}/{port}"))
        return addrs

    def expand_wildcard_address(addr: Multiaddr, port: int | None = None):
        if port is None:
            return [addr]
        addr_str = str(addr).rsplit("/", 1)[0]
        return [Multiaddr(addr_str + f"/{port}")]

    def get_optimal_binding_address(port: int, protocol: str = "tcp"):
        # Try to get a non-loopback address first
        interfaces = get_available_interfaces(port, protocol)
        for addr in interfaces:
            if "127.0.0.1" not in str(addr):
                return addr
        # Fallback to loopback if no other interfaces found
        return Multiaddr(f"/ip4/127.0.0.1/{protocol}/{port}")

    def get_wildcard_address(port: int, protocol: str = "tcp"):
        return Multiaddr(f"/ip4/0.0.0.0/{protocol}/{port}")


def main() -> None:
    port = 8080
    interfaces = get_available_interfaces(port)
    print(f"Discovered interfaces for port {port}:")
    for a in interfaces:
        print(f"  - {a}")

    # Demonstrate wildcard address as a feature
    wildcard_v4 = get_wildcard_address(port)
    print(f"\nWildcard address (feature): {wildcard_v4}")

    expanded_v4 = expand_wildcard_address(wildcard_v4)
    print("\nExpanded IPv4 wildcard:")
    for a in expanded_v4:
        print(f"  - {a}")

    wildcard_v6 = Multiaddr(f"/ip6/::/tcp/{port}")
    expanded_v6 = expand_wildcard_address(wildcard_v6)
    print("\nExpanded IPv6 wildcard:")
    for a in expanded_v6:
        print(f"  - {a}")

    print("\nOptimal binding address heuristic result:")
    print(f"  -> {get_optimal_binding_address(port)}")

    override_port = 9000
    overridden = expand_wildcard_address(wildcard_v4, port=override_port)
    print(f"\nPort override expansion to {override_port}:")
    for a in overridden:
        print(f"  - {a}")


if __name__ == "__main__":
    main()

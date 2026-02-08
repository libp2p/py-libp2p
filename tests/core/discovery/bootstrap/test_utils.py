#!/usr/bin/env python3
"""
Test bootstrap address validation and DNS protocol detection.
"""

from unittest.mock import MagicMock

from multiaddr import Multiaddr

from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery
from libp2p.discovery.bootstrap.utils import (
    parse_bootstrap_peer_info,
    validate_bootstrap_addresses,
)


def test_validate_addresses():
    """Test validation with a mix of valid and invalid addresses in one list."""
    addresses = [
        # Valid - using proper peer IDs
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
        "/ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
        # Invalid
        "invalid-address",
        "/ip4/192.168.1.1/tcp/4001",  # Missing p2p part
        "",  # Empty
        "/ip4/127.0.0.1/tcp/4001/p2p/InvalidPeerID",  # Bad peer ID
    ]
    valid_expected = [
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
        "/ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
    ]
    validated = validate_bootstrap_addresses(addresses)
    assert validated == valid_expected, (
        f"Expected only valid addresses, got: {validated}"
    )
    for addr in addresses:
        peer_info = parse_bootstrap_peer_info(addr)
        if addr in valid_expected:
            assert peer_info is not None and peer_info.peer_id is not None, (
                f"Should parse valid address: {addr}"
            )
        else:
            assert peer_info is None, f"Should not parse invalid address: {addr}"


def test_is_dns_addr_dns_protocols():
    """Test that is_dns_addr recognizes dns, dns4, dns6, and dnsaddr."""
    swarm = MagicMock()
    discovery = BootstrapDiscovery(swarm, [])

    # DNS protocol variants (libp2p spec) - use parseable multiaddrs
    dns_addrs = [
        "/dns4/example.com/tcp/443",
        "/dns6/example.com/tcp/443",
        "/dns/example.com/tcp/80",
        "/dnsaddr/example.com/tcp/443",
    ]
    for addr_str in dns_addrs:
        maddr = Multiaddr(addr_str)
        assert discovery.is_dns_addr(maddr), (
            f"Expected DNS address: {addr_str}"
        )

    # Non-DNS addresses
    non_dns_addrs = [
        "/ip4/127.0.0.1/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
        "/ip6/::1/tcp/4001",
    ]
    for addr_str in non_dns_addrs:
        maddr = Multiaddr(addr_str)
        assert not discovery.is_dns_addr(maddr), (
            f"Expected non-DNS address: {addr_str}"
        )

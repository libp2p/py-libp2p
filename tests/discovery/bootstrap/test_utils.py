#!/usr/bin/env python3
"""
Test bootstrap address validation
"""

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

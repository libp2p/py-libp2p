#!/usr/bin/env python3
"""
Test the full bootstrap discovery integration
"""

import logging
import secrets

import pytest

from libp2p import new_host
from libp2p.abc import PeerInfo
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.discovery.events.peerDiscovery import peerDiscovery
from libp2p.host.basic_host import BasicHost

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bootstrap_test")


def on_peer_discovery(peer_info: PeerInfo) -> None:
    """Handler for peer discovery events."""
    logger.info(f"🔍 Discovered peer: {peer_info.peer_id}")
    logger.info(f"   Addresses: {[str(addr) for addr in peer_info.addrs]}")


@pytest.mark.trio
async def test_bootstrap_integration():
    """Test bootstrap integration with new_host"""
    print("🧪 Testing Bootstrap Integration")

    # Test bootstrap addresses
    bootstrap_addrs = [
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SznbYGzPwp8qDrq",
        "/ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
    ]

    # Generate key pair
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Register peer discovery handler
    peerDiscovery.register_peer_discovered_handler(on_peer_discovery)

    print(f"🌐 Testing with {len(bootstrap_addrs)} bootstrap peers")

    # Create host with bootstrap
    host = new_host(key_pair=key_pair, bootstrap=bootstrap_addrs)

    print("✅ Successfully created host with bootstrap")
    print(f"📍 Host peer ID: {host.get_id()}")
    print("🔗 Bootstrap discovery should process peers when host starts")

    # Verify bootstrap discovery is set up (cast to BasicHost for type checking)
    assert isinstance(host, BasicHost), "Host should be a BasicHost instance"
    assert hasattr(host, "bootstrap"), "Host should have bootstrap attribute"
    assert host.bootstrap is not None, "Bootstrap discovery should be initialized"
    assert len(host.bootstrap.bootstrap_addrs) == len(bootstrap_addrs), (
        "Bootstrap addresses should match"
    )

    print("🎉 Bootstrap integration test completed successfully!")


def test_bootstrap_no_addresses():
    """Test that bootstrap is not initialized when no addresses provided"""
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create host without bootstrap
    host = new_host(key_pair=key_pair)

    # Verify bootstrap is not initialized
    assert isinstance(host, BasicHost)
    assert not hasattr(host, "bootstrap") or host.bootstrap is None, (
        "Bootstrap should not be initialized when no addresses provided"
    )

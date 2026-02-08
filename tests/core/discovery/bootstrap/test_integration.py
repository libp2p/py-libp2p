#!/usr/bin/env python3
"""
Test the full bootstrap discovery integration.
"""

import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.host.basic_host import BasicHost


# Valid peer IDs (must be valid CIDs; from test_utils.py validated set)
BOOTSTRAP_PEER_ID = "QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"


@pytest.mark.trio
async def test_bootstrap_integration():
    """Test bootstrap integration with new_host"""
    # Test bootstrap addresses (use validated peer IDs from test_utils)
    bootstrap_addrs = [
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
        "/ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
    ]

    # Generate key pair
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create host with bootstrap
    host = new_host(key_pair=key_pair, bootstrap=bootstrap_addrs)

    # Verify bootstrap discovery is set up (cast to BasicHost for type checking)
    assert isinstance(host, BasicHost), "Host should be a BasicHost instance"
    assert hasattr(host, "bootstrap"), "Host should have bootstrap attribute"
    assert host.bootstrap is not None, "Bootstrap discovery should be initialized"
    assert len(host.bootstrap.bootstrap_addrs) == len(bootstrap_addrs), (
        "Bootstrap addresses should match"
    )


@pytest.mark.trio
async def test_bootstrap_integration_with_dns_addresses():
    """Test that new_host accepts dns4, dns6, and dnsaddr bootstrap addresses."""
    bootstrap_addrs = [
        "/ip4/104.131.131.82/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
        "/dns4/bootstrap.example.com/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
        "/dns6/bootstrap.example.com/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    ]

    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)
    host = new_host(key_pair=key_pair, bootstrap=bootstrap_addrs)

    assert isinstance(host, BasicHost)
    assert host.bootstrap is not None
    # After validation, all four addresses are valid (parseable + have p2p)
    assert len(host.bootstrap.bootstrap_addrs) == len(bootstrap_addrs), (
        "Bootstrap should accept IP and DNS (dns4, dns6, dnsaddr) addresses"
    )


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


@pytest.mark.trio
async def test_bootstrap_dns_resolution_failure_continues():
    """Test that when DNS resolution fails for one address, bootstrap continues with others."""
    from libp2p.discovery.bootstrap.bootstrap import (
        BootstrapDiscovery,
        resolver,
    )

    # First address: DNS that will "fail"; second: DNS that "succeeds" with a resolved IP
    bootstrap_addrs: list[str] = [
        "/dns4/fail.example.com/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
        "/dns4/ok.example.com/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
    ]
    resolved_ok = [
        Multiaddr(f"/ip4/104.131.131.82/tcp/4001/p2p/{BOOTSTRAP_PEER_ID}"),
    ]

    swarm = MagicMock()
    swarm.get_peer_id.return_value = None  # so we're not "our own peer"
    swarm.connections = {}
    swarm.peerstore = MagicMock()
    swarm.dial_peer = AsyncMock()

    call_count = 0

    async def mock_resolve(maddr):
        nonlocal call_count
        call_count += 1
        s = str(maddr)
        if "fail.example.com" in s:
            raise OSError("DNS resolution failed (mocked)")
        if "ok.example.com" in s:
            return resolved_ok
        return []

    with patch.object(resolver, "resolve", side_effect=mock_resolve):
        discovery = BootstrapDiscovery(swarm, bootstrap_addrs)
        await discovery.start()

    # Resolver should have been called for both addresses
    assert call_count == 2
    # First call raised; second returned resolved addrs and add_addr was used
    swarm.peerstore.add_addrs.assert_called()


@pytest.mark.trio
async def test_bootstrap_dns_empty_results_continues():
    """Test that when DNS resolution returns no addresses, bootstrap continues without crashing."""
    from libp2p.discovery.bootstrap.bootstrap import (
        BootstrapDiscovery,
        resolver,
    )

    bootstrap_addrs: list[str] = [
        "/dns4/empty.example.com/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
        "/ip4/104.131.131.82/tcp/4001/p2p/" + BOOTSTRAP_PEER_ID,
    ]

    swarm = MagicMock()
    swarm.get_peer_id.return_value = None
    swarm.connections = {}
    swarm.peerstore = MagicMock()
    swarm.dial_peer = AsyncMock()

    async def mock_resolve(maddr):
        s = str(maddr)
        if "empty.example.com" in s:
            return []  # No addresses resolved
        return [Multiaddr(f"/ip4/104.131.131.82/tcp/4001/p2p/{BOOTSTRAP_PEER_ID}")]

    with patch.object(resolver, "resolve", side_effect=mock_resolve):
        discovery = BootstrapDiscovery(swarm, bootstrap_addrs)
        await discovery.start()

    # IP address path (non-DNS) should have been processed
    swarm.peerstore.add_addrs.assert_called()

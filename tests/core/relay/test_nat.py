"""Tests for NAT traversal utilities."""

from unittest.mock import MagicMock

import pytest
from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.nat import (
    ReachabilityChecker,
    extract_ip_from_multiaddr,
    ip_to_int,
    is_ip_in_range,
    is_private_ip,
)


def test_ip_to_int_ipv4():
    """Test converting IPv4 addresses to integers."""
    assert ip_to_int("192.168.1.1") == 3232235777
    assert ip_to_int("10.0.0.1") == 167772161
    assert ip_to_int("127.0.0.1") == 2130706433


def test_ip_to_int_ipv6():
    """Test converting IPv6 addresses to integers."""
    # Test with a simple IPv6 address
    ipv6_int = ip_to_int("::1")
    assert isinstance(ipv6_int, int)
    assert ipv6_int > 0


def test_ip_to_int_invalid():
    """Test handling of invalid IP addresses."""
    with pytest.raises(ValueError):
        ip_to_int("invalid-ip")


def test_is_ip_in_range():
    """Test IP range checking."""
    # Test within range
    assert is_ip_in_range("192.168.1.5", "192.168.1.1", "192.168.1.10") is True
    assert is_ip_in_range("10.0.0.5", "10.0.0.0", "10.0.0.255") is True

    # Test outside range
    assert is_ip_in_range("192.168.2.5", "192.168.1.1", "192.168.1.10") is False
    assert is_ip_in_range("8.8.8.8", "10.0.0.0", "10.0.0.255") is False


def test_is_ip_in_range_invalid():
    """Test IP range checking with invalid inputs."""
    assert is_ip_in_range("invalid", "192.168.1.1", "192.168.1.10") is False
    assert is_ip_in_range("192.168.1.5", "invalid", "192.168.1.10") is False


def test_is_private_ip():
    """Test private IP detection."""
    # Private IPs
    assert is_private_ip("192.168.1.1") is True
    assert is_private_ip("10.0.0.1") is True
    assert is_private_ip("172.16.0.1") is True
    assert is_private_ip("127.0.0.1") is True  # Loopback
    assert is_private_ip("169.254.1.1") is True  # Link-local

    # Public IPs
    assert is_private_ip("8.8.8.8") is False
    assert is_private_ip("1.1.1.1") is False
    assert is_private_ip("208.67.222.222") is False


def test_extract_ip_from_multiaddr():
    """Test IP extraction from multiaddrs."""
    # IPv4 addresses
    addr1 = Multiaddr("/ip4/192.168.1.1/tcp/1234")
    assert extract_ip_from_multiaddr(addr1) == "192.168.1.1"

    addr2 = Multiaddr("/ip4/10.0.0.1/udp/5678")
    assert extract_ip_from_multiaddr(addr2) == "10.0.0.1"

    # IPv6 addresses
    addr3 = Multiaddr("/ip6/::1/tcp/1234")
    assert extract_ip_from_multiaddr(addr3) == "::1"

    addr4 = Multiaddr("/ip6/2001:db8::1/udp/5678")
    assert extract_ip_from_multiaddr(addr4) == "2001:db8::1"

    # No IP address
    addr5 = Multiaddr("/dns4/example.com/tcp/1234")
    assert extract_ip_from_multiaddr(addr5) is None

    # Complex multiaddr (without p2p to avoid base58 issues)
    addr6 = Multiaddr("/ip4/192.168.1.1/tcp/1234/udp/5678")
    assert extract_ip_from_multiaddr(addr6) == "192.168.1.1"


def test_reachability_checker_init():
    """Test ReachabilityChecker initialization."""
    mock_host = MagicMock()
    checker = ReachabilityChecker(mock_host)

    assert checker.host == mock_host
    assert checker._peer_reachability == {}
    assert checker._known_public_peers == set()


def test_reachability_checker_is_addr_public():
    """Test public address detection."""
    mock_host = MagicMock()
    checker = ReachabilityChecker(mock_host)

    # Public addresses
    public_addr1 = Multiaddr("/ip4/8.8.8.8/tcp/1234")
    assert checker.is_addr_public(public_addr1) is True

    public_addr2 = Multiaddr("/ip4/1.1.1.1/udp/5678")
    assert checker.is_addr_public(public_addr2) is True

    # Private addresses
    private_addr1 = Multiaddr("/ip4/192.168.1.1/tcp/1234")
    assert checker.is_addr_public(private_addr1) is False

    private_addr2 = Multiaddr("/ip4/10.0.0.1/udp/5678")
    assert checker.is_addr_public(private_addr2) is False

    private_addr3 = Multiaddr("/ip4/127.0.0.1/tcp/1234")
    assert checker.is_addr_public(private_addr3) is False

    # No IP address
    dns_addr = Multiaddr("/dns4/example.com/tcp/1234")
    assert checker.is_addr_public(dns_addr) is False


def test_reachability_checker_get_public_addrs():
    """Test filtering for public addresses."""
    mock_host = MagicMock()
    checker = ReachabilityChecker(mock_host)

    addrs = [
        Multiaddr("/ip4/8.8.8.8/tcp/1234"),  # Public
        Multiaddr("/ip4/192.168.1.1/tcp/1234"),  # Private
        Multiaddr("/ip4/1.1.1.1/udp/5678"),  # Public
        Multiaddr("/ip4/10.0.0.1/tcp/1234"),  # Private
        Multiaddr("/dns4/example.com/tcp/1234"),  # DNS
    ]

    public_addrs = checker.get_public_addrs(addrs)
    assert len(public_addrs) == 2
    assert Multiaddr("/ip4/8.8.8.8/tcp/1234") in public_addrs
    assert Multiaddr("/ip4/1.1.1.1/udp/5678") in public_addrs


@pytest.mark.trio
async def test_check_peer_reachability_connected_direct():
    """Test peer reachability when directly connected."""
    mock_host = MagicMock()
    mock_network = MagicMock()
    mock_host.get_network.return_value = mock_network

    peer_id = ID(b"test-peer-id")
    mock_conn = MagicMock()
    mock_conn.get_transport_addresses.return_value = [
        Multiaddr("/ip4/192.168.1.1/tcp/1234")  # Direct connection
    ]

    mock_network.connections = {peer_id: mock_conn}

    checker = ReachabilityChecker(mock_host)
    result = await checker.check_peer_reachability(peer_id)

    assert result is True
    assert checker._peer_reachability[peer_id] is True


@pytest.mark.trio
async def test_check_peer_reachability_connected_relay():
    """Test peer reachability when connected through relay."""
    mock_host = MagicMock()
    mock_network = MagicMock()
    mock_host.get_network.return_value = mock_network

    peer_id = ID(b"test-peer-id")
    mock_conn = MagicMock()
    mock_conn.get_transport_addresses.return_value = [
        Multiaddr("/p2p-circuit/ip4/192.168.1.1/tcp/1234")  # Relay connection
    ]

    mock_network.connections = {peer_id: mock_conn}

    # Mock peerstore with public addresses
    mock_peerstore = MagicMock()
    mock_peerstore.addrs.return_value = [
        Multiaddr("/ip4/8.8.8.8/tcp/1234")  # Public address
    ]
    mock_host.get_peerstore.return_value = mock_peerstore

    checker = ReachabilityChecker(mock_host)
    result = await checker.check_peer_reachability(peer_id)

    assert result is True
    assert checker._peer_reachability[peer_id] is True


@pytest.mark.trio
async def test_check_peer_reachability_not_connected():
    """Test peer reachability when not connected."""
    mock_host = MagicMock()
    mock_network = MagicMock()
    mock_host.get_network.return_value = mock_network

    peer_id = ID(b"test-peer-id")
    mock_network.connections = {}  # No connections

    checker = ReachabilityChecker(mock_host)
    result = await checker.check_peer_reachability(peer_id)

    assert result is False
    # When not connected, the method doesn't add to cache
    assert peer_id not in checker._peer_reachability


@pytest.mark.trio
async def test_check_peer_reachability_cached():
    """Test that peer reachability results are cached."""
    mock_host = MagicMock()
    checker = ReachabilityChecker(mock_host)

    peer_id = ID(b"test-peer-id")
    checker._peer_reachability[peer_id] = True

    result = await checker.check_peer_reachability(peer_id)
    assert result is True

    # Should not call host methods when cached
    mock_host.get_network.assert_not_called()


@pytest.mark.trio
async def test_check_self_reachability_with_public_addrs():
    """Test self reachability when host has public addresses."""
    mock_host = MagicMock()
    mock_host.get_addrs.return_value = [
        Multiaddr("/ip4/8.8.8.8/tcp/1234"),  # Public
        Multiaddr("/ip4/192.168.1.1/tcp/1234"),  # Private
        Multiaddr("/ip4/1.1.1.1/udp/5678"),  # Public
    ]

    checker = ReachabilityChecker(mock_host)
    is_reachable, public_addrs = await checker.check_self_reachability()

    assert is_reachable is True
    assert len(public_addrs) == 2
    assert Multiaddr("/ip4/8.8.8.8/tcp/1234") in public_addrs
    assert Multiaddr("/ip4/1.1.1.1/udp/5678") in public_addrs


@pytest.mark.trio
async def test_check_self_reachability_no_public_addrs():
    """Test self reachability when host has no public addresses."""
    mock_host = MagicMock()
    mock_host.get_addrs.return_value = [
        Multiaddr("/ip4/192.168.1.1/tcp/1234"),  # Private
        Multiaddr("/ip4/10.0.0.1/udp/5678"),  # Private
        Multiaddr("/ip4/127.0.0.1/tcp/1234"),  # Loopback
    ]

    checker = ReachabilityChecker(mock_host)
    is_reachable, public_addrs = await checker.check_self_reachability()

    assert is_reachable is False
    assert len(public_addrs) == 0


@pytest.mark.trio
async def test_check_peer_reachability_multiple_connections():
    """Test peer reachability with multiple connections."""
    mock_host = MagicMock()
    mock_network = MagicMock()
    mock_host.get_network.return_value = mock_network

    peer_id = ID(b"test-peer-id")
    mock_conn1 = MagicMock()
    mock_conn1.get_transport_addresses.return_value = [
        Multiaddr("/p2p-circuit/ip4/192.168.1.1/tcp/1234")  # Relay
    ]

    mock_conn2 = MagicMock()
    mock_conn2.get_transport_addresses.return_value = [
        Multiaddr("/ip4/192.168.1.1/tcp/1234")  # Direct
    ]

    mock_network.connections = {peer_id: [mock_conn1, mock_conn2]}

    checker = ReachabilityChecker(mock_host)
    result = await checker.check_peer_reachability(peer_id)

    assert result is True
    assert checker._peer_reachability[peer_id] is True

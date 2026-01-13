"""Tests for multiaddr utility functions."""

import pytest
from multiaddr import Multiaddr

from libp2p.utils.multiaddr_utils import (
    extract_ip_and_protocol,
    extract_ip_from_multiaddr,
    get_ip_protocol_from_address,
    get_ip_protocol_from_multiaddr,
    is_ipv6_address,
    multiaddr_from_socket_address,
    validate_ip_address,
)


class TestExtractIpFromMultiaddr:
    """Tests for extract_ip_from_multiaddr function."""

    def test_extract_ipv4(self):
        """Test extraction of IPv4 address."""
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080")
        assert extract_ip_from_multiaddr(maddr) == "127.0.0.1"

    def test_extract_ipv6(self):
        """Test extraction of IPv6 address."""
        maddr = Multiaddr("/ip6/::1/tcp/8080")
        assert extract_ip_from_multiaddr(maddr) == "::1"

    def test_extract_ipv6_full(self):
        """Test extraction of full IPv6 address."""
        maddr = Multiaddr("/ip6/2001:db8::1/tcp/8080")
        assert extract_ip_from_multiaddr(maddr) == "2001:db8::1"

    def test_extract_no_ip(self):
        """Test extraction when no IP is present."""
        maddr = Multiaddr("/dns4/example.com/tcp/8080")
        assert extract_ip_from_multiaddr(maddr) is None


class TestExtractIpAndProtocol:
    """Tests for extract_ip_and_protocol function."""

    def test_extract_ipv4(self):
        """Test extraction of IPv4 address and protocol."""
        maddr = Multiaddr("/ip4/192.168.1.1/tcp/8080")
        ip, proto = extract_ip_and_protocol(maddr)
        assert ip == "192.168.1.1"
        assert proto == "ip4"

    def test_extract_ipv6(self):
        """Test extraction of IPv6 address and protocol."""
        maddr = Multiaddr("/ip6/fe80::1/tcp/8080")
        ip, proto = extract_ip_and_protocol(maddr)
        assert ip == "fe80::1"
        assert proto == "ip6"

    def test_extract_no_ip(self):
        """Test extraction when no IP is present."""
        maddr = Multiaddr("/dns4/example.com/tcp/8080")
        ip, proto = extract_ip_and_protocol(maddr)
        assert ip is None
        assert proto is None


class TestGetIpProtocolFromMultiaddr:
    """Tests for get_ip_protocol_from_multiaddr function."""

    def test_ipv4_protocol(self):
        """Test detection of IPv4 protocol."""
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080")
        assert get_ip_protocol_from_multiaddr(maddr) == "ip4"

    def test_ipv6_protocol(self):
        """Test detection of IPv6 protocol."""
        maddr = Multiaddr("/ip6/::1/tcp/8080")
        assert get_ip_protocol_from_multiaddr(maddr) == "ip6"

    def test_no_ip_protocol(self):
        """Test when no IP protocol is present."""
        maddr = Multiaddr("/dns4/example.com/tcp/8080")
        assert get_ip_protocol_from_multiaddr(maddr) is None


class TestGetIpProtocolFromAddress:
    """Tests for get_ip_protocol_from_address function."""

    def test_ipv4_address(self):
        """Test detection of IPv4 address."""
        assert get_ip_protocol_from_address("127.0.0.1") == "ip4"
        assert get_ip_protocol_from_address("192.168.1.1") == "ip4"
        assert get_ip_protocol_from_address("0.0.0.0") == "ip4"

    def test_ipv6_address(self):
        """Test detection of IPv6 address."""
        assert get_ip_protocol_from_address("::1") == "ip6"
        assert get_ip_protocol_from_address("::") == "ip6"
        assert get_ip_protocol_from_address("2001:db8::1") == "ip6"
        assert get_ip_protocol_from_address("fe80::1%eth0") == "ip6"


class TestIsIpv6Address:
    """Tests for is_ipv6_address function."""

    def test_ipv4_addresses(self):
        """Test that IPv4 addresses return False."""
        assert is_ipv6_address("127.0.0.1") is False
        assert is_ipv6_address("192.168.1.1") is False
        assert is_ipv6_address("0.0.0.0") is False

    def test_ipv6_addresses(self):
        """Test that IPv6 addresses return True."""
        assert is_ipv6_address("::1") is True
        assert is_ipv6_address("::") is True
        assert is_ipv6_address("2001:db8::1") is True
        assert is_ipv6_address("fe80::1") is True


class TestValidateIpAddress:
    """Tests for validate_ip_address function."""

    def test_valid_ipv4(self):
        """Test validation of valid IPv4 address."""
        addr, version = validate_ip_address("192.168.1.1")
        assert addr == "192.168.1.1"
        assert version == 4

    def test_valid_ipv6(self):
        """Test validation of valid IPv6 address."""
        addr, version = validate_ip_address("::1")
        assert addr == "::1"
        assert version == 6

    def test_valid_ipv6_full(self):
        """Test validation of full IPv6 address."""
        addr, version = validate_ip_address("2001:db8::1")
        assert addr == "2001:db8::1"
        assert version == 6

    def test_invalid_address(self):
        """Test validation of invalid address raises ValueError."""
        with pytest.raises(ValueError):
            validate_ip_address("not-an-ip")


class TestMultiaddrFromSocketAddress:
    """Tests for multiaddr_from_socket_address function."""

    def test_ipv4_tcp(self):
        """Test creating multiaddr from IPv4 socket address."""
        maddr = multiaddr_from_socket_address("127.0.0.1", 8080)
        assert str(maddr) == "/ip4/127.0.0.1/tcp/8080"

    def test_ipv6_tcp(self):
        """Test creating multiaddr from IPv6 socket address."""
        maddr = multiaddr_from_socket_address("::1", 8080)
        assert str(maddr) == "/ip6/::1/tcp/8080"

    def test_ipv4_udp(self):
        """Test creating multiaddr from IPv4 socket address with UDP."""
        maddr = multiaddr_from_socket_address("127.0.0.1", 8080, "udp")
        assert str(maddr) == "/ip4/127.0.0.1/udp/8080"

    def test_ipv6_udp(self):
        """Test creating multiaddr from IPv6 socket address with UDP."""
        maddr = multiaddr_from_socket_address("2001:db8::1", 8080, "udp")
        assert str(maddr) == "/ip6/2001:db8::1/udp/8080"

"""
Test suite for QUIC multiaddr utilities.
Focused tests covering essential functionality required for QUIC transport.
"""

import pytest
from multiaddr import Multiaddr

from libp2p.custom_types import TProtocol
from libp2p.transport.quic.exceptions import (
    QUICInvalidMultiaddrError,
    QUICUnsupportedVersionError,
)
from libp2p.transport.quic.utils import (
    create_quic_multiaddr,
    get_alpn_protocols,
    is_quic_multiaddr,
    multiaddr_to_quic_version,
    normalize_quic_multiaddr,
    quic_multiaddr_to_endpoint,
    quic_version_to_wire_format,
)


class TestIsQuicMultiaddr:
    """Test QUIC multiaddr detection."""

    def test_valid_quic_v1_multiaddrs(self):
        """Test valid QUIC v1 multiaddrs are detected."""
        valid_addrs = [
            "/ip4/127.0.0.1/udp/4001/quic-v1",
            "/ip4/192.168.1.1/udp/8080/quic-v1",
            "/ip6/::1/udp/4001/quic-v1",
            "/ip6/2001:db8::1/udp/5000/quic-v1",
        ]

        for addr_str in valid_addrs:
            maddr = Multiaddr(addr_str)
            assert is_quic_multiaddr(maddr), f"Should detect {addr_str} as QUIC"

    def test_valid_quic_draft29_multiaddrs(self):
        """Test valid QUIC draft-29 multiaddrs are detected."""
        valid_addrs = [
            "/ip4/127.0.0.1/udp/4001/quic",
            "/ip4/10.0.0.1/udp/9000/quic",
            "/ip6/::1/udp/4001/quic",
            "/ip6/fe80::1/udp/6000/quic",
        ]

        for addr_str in valid_addrs:
            maddr = Multiaddr(addr_str)
            assert is_quic_multiaddr(maddr), f"Should detect {addr_str} as QUIC"

    def test_invalid_multiaddrs(self):
        """Test non-QUIC multiaddrs are not detected."""
        invalid_addrs = [
            "/ip4/127.0.0.1/tcp/4001",  # TCP, not QUIC
            "/ip4/127.0.0.1/udp/4001",  # UDP without QUIC
            "/ip4/127.0.0.1/udp/4001/ws",  # WebSocket
            "/ip4/127.0.0.1/quic-v1",  # Missing UDP
            "/udp/4001/quic-v1",  # Missing IP
            "/dns4/example.com/tcp/443/tls",  # Completely different
        ]

        for addr_str in invalid_addrs:
            maddr = Multiaddr(addr_str)
            assert not is_quic_multiaddr(maddr), f"Should not detect {addr_str} as QUIC"


class TestQuicMultiaddrToEndpoint:
    """Test endpoint extraction from QUIC multiaddrs."""

    def test_ipv4_extraction(self):
        """Test IPv4 host/port extraction."""
        test_cases = [
            ("/ip4/127.0.0.1/udp/4001/quic-v1", ("127.0.0.1", 4001)),
            ("/ip4/192.168.1.100/udp/8080/quic", ("192.168.1.100", 8080)),
            ("/ip4/10.0.0.1/udp/9000/quic-v1", ("10.0.0.1", 9000)),
        ]

        for addr_str, expected in test_cases:
            maddr = Multiaddr(addr_str)
            result = quic_multiaddr_to_endpoint(maddr)
            assert result == expected, f"Failed for {addr_str}"

    def test_ipv6_extraction(self):
        """Test IPv6 host/port extraction."""
        test_cases = [
            ("/ip6/::1/udp/4001/quic-v1", ("::1", 4001)),
            ("/ip6/2001:db8::1/udp/5000/quic", ("2001:db8::1", 5000)),
        ]

        for addr_str, expected in test_cases:
            maddr = Multiaddr(addr_str)
            result = quic_multiaddr_to_endpoint(maddr)
            assert result == expected, f"Failed for {addr_str}"

    def test_invalid_multiaddr_raises_error(self):
        """Test invalid multiaddrs raise appropriate errors."""
        invalid_addrs = [
            "/ip4/127.0.0.1/tcp/4001",  # Not QUIC
            "/ip4/127.0.0.1/udp/4001",  # Missing QUIC protocol
        ]

        for addr_str in invalid_addrs:
            maddr = Multiaddr(addr_str)
            with pytest.raises(QUICInvalidMultiaddrError):
                quic_multiaddr_to_endpoint(maddr)


class TestMultiaddrToQuicVersion:
    """Test QUIC version extraction."""

    def test_quic_v1_detection(self):
        """Test QUIC v1 version detection."""
        addrs = [
            "/ip4/127.0.0.1/udp/4001/quic-v1",
            "/ip6/::1/udp/5000/quic-v1",
        ]

        for addr_str in addrs:
            maddr = Multiaddr(addr_str)
            version = multiaddr_to_quic_version(maddr)
            assert version == "quic-v1", f"Should detect quic-v1 for {addr_str}"

    def test_quic_draft29_detection(self):
        """Test QUIC draft-29 version detection."""
        addrs = [
            "/ip4/127.0.0.1/udp/4001/quic",
            "/ip6/::1/udp/5000/quic",
        ]

        for addr_str in addrs:
            maddr = Multiaddr(addr_str)
            version = multiaddr_to_quic_version(maddr)
            assert version == "quic", f"Should detect quic for {addr_str}"

    def test_non_quic_raises_error(self):
        """Test non-QUIC multiaddrs raise error."""
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/4001")
        with pytest.raises(QUICInvalidMultiaddrError):
            multiaddr_to_quic_version(maddr)


class TestCreateQuicMultiaddr:
    """Test QUIC multiaddr creation."""

    def test_ipv4_creation(self):
        """Test IPv4 QUIC multiaddr creation."""
        test_cases = [
            ("127.0.0.1", 4001, "quic-v1", "/ip4/127.0.0.1/udp/4001/quic-v1"),
            ("192.168.1.1", 8080, "quic", "/ip4/192.168.1.1/udp/8080/quic"),
            ("10.0.0.1", 9000, "/quic-v1", "/ip4/10.0.0.1/udp/9000/quic-v1"),
        ]

        for host, port, version, expected in test_cases:
            result = create_quic_multiaddr(host, port, version)
            assert str(result) == expected

    def test_ipv6_creation(self):
        """Test IPv6 QUIC multiaddr creation."""
        test_cases = [
            ("::1", 4001, "quic-v1", "/ip6/::1/udp/4001/quic-v1"),
            ("2001:db8::1", 5000, "quic", "/ip6/2001:db8::1/udp/5000/quic"),
        ]

        for host, port, version, expected in test_cases:
            result = create_quic_multiaddr(host, port, version)
            assert str(result) == expected

    def test_default_version(self):
        """Test default version is quic-v1."""
        result = create_quic_multiaddr("127.0.0.1", 4001)
        expected = "/ip4/127.0.0.1/udp/4001/quic-v1"
        assert str(result) == expected

    def test_invalid_inputs_raise_errors(self):
        """Test invalid inputs raise appropriate errors."""
        # Invalid IP
        with pytest.raises(QUICInvalidMultiaddrError):
            create_quic_multiaddr("invalid-ip", 4001)

        # Invalid port
        with pytest.raises(QUICInvalidMultiaddrError):
            create_quic_multiaddr("127.0.0.1", 70000)

        with pytest.raises(QUICInvalidMultiaddrError):
            create_quic_multiaddr("127.0.0.1", -1)

        # Invalid version
        with pytest.raises(QUICInvalidMultiaddrError):
            create_quic_multiaddr("127.0.0.1", 4001, "invalid-version")


class TestQuicVersionToWireFormat:
    """Test QUIC version to wire format conversion."""

    def test_supported_versions(self):
        """Test supported version conversions."""
        test_cases = [
            ("quic-v1", 0x00000001),  # RFC 9000
            ("quic", 0xFF00001D),  # draft-29
        ]

        for version, expected_wire in test_cases:
            result = quic_version_to_wire_format(TProtocol(version))
            assert result == expected_wire, f"Failed for version {version}"

    def test_unsupported_version_raises_error(self):
        """Test unsupported versions raise error."""
        with pytest.raises(QUICUnsupportedVersionError):
            quic_version_to_wire_format(TProtocol("unsupported-version"))


class TestGetAlpnProtocols:
    """Test ALPN protocol retrieval."""

    def test_returns_libp2p_protocols(self):
        """Test returns expected libp2p ALPN protocols."""
        protocols = get_alpn_protocols()
        assert protocols == ["libp2p"]
        assert isinstance(protocols, list)

    def test_returns_copy(self):
        """Test returns a copy, not the original list."""
        protocols1 = get_alpn_protocols()
        protocols2 = get_alpn_protocols()

        # Modify one list
        protocols1.append("test")

        # Other list should be unchanged
        assert protocols2 == ["libp2p"]


class TestNormalizeQuicMultiaddr:
    """Test QUIC multiaddr normalization."""

    def test_already_normalized(self):
        """Test already normalized multiaddrs pass through."""
        addr_str = "/ip4/127.0.0.1/udp/4001/quic-v1"
        maddr = Multiaddr(addr_str)

        result = normalize_quic_multiaddr(maddr)
        assert str(result) == addr_str

    def test_normalize_different_versions(self):
        """Test normalization works for different QUIC versions."""
        test_cases = [
            "/ip4/127.0.0.1/udp/4001/quic-v1",
            "/ip4/127.0.0.1/udp/4001/quic",
            "/ip6/::1/udp/5000/quic-v1",
        ]

        for addr_str in test_cases:
            maddr = Multiaddr(addr_str)
            result = normalize_quic_multiaddr(maddr)

            # Should be valid QUIC multiaddr
            assert is_quic_multiaddr(result)

            # Should be parseable
            host, port = quic_multiaddr_to_endpoint(result)
            version = multiaddr_to_quic_version(result)

            # Should match original
            orig_host, orig_port = quic_multiaddr_to_endpoint(maddr)
            orig_version = multiaddr_to_quic_version(maddr)

            assert host == orig_host
            assert port == orig_port
            assert version == orig_version

    def test_non_quic_raises_error(self):
        """Test non-QUIC multiaddrs raise error."""
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/4001")
        with pytest.raises(QUICInvalidMultiaddrError):
            normalize_quic_multiaddr(maddr)


class TestIntegration:
    """Integration tests for utility functions working together."""

    def test_round_trip_conversion(self):
        """Test creating and parsing multiaddrs works correctly."""
        test_cases = [
            ("127.0.0.1", 4001, "quic-v1"),
            ("::1", 5000, "quic"),
            ("192.168.1.100", 8080, "quic-v1"),
        ]

        for host, port, version in test_cases:
            # Create multiaddr
            maddr = create_quic_multiaddr(host, port, version)

            # Should be detected as QUIC
            assert is_quic_multiaddr(maddr)

            # Should extract original values
            extracted_host, extracted_port = quic_multiaddr_to_endpoint(maddr)
            extracted_version = multiaddr_to_quic_version(maddr)

            assert extracted_host == host
            assert extracted_port == port
            assert extracted_version == version

            # Should normalize to same value
            normalized = normalize_quic_multiaddr(maddr)
            assert str(normalized) == str(maddr)

    def test_wire_format_integration(self):
        """Test wire format conversion works with version detection."""
        addr_str = "/ip4/127.0.0.1/udp/4001/quic-v1"
        maddr = Multiaddr(addr_str)

        # Extract version and convert to wire format
        version = multiaddr_to_quic_version(maddr)
        wire_format = quic_version_to_wire_format(version)

        # Should be QUIC v1 wire format
        assert wire_format == 0x00000001

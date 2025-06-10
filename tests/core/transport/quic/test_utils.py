import pytest
from multiaddr.multiaddr import Multiaddr

from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.utils import (
    create_quic_multiaddr,
    is_quic_multiaddr,
    multiaddr_to_quic_version,
    quic_multiaddr_to_endpoint,
)


class TestQUICUtils:
    """Test suite for QUIC utility functions."""

    def test_is_quic_multiaddr(self):
        """Test QUIC multiaddr validation."""
        # Valid QUIC multiaddrs
        valid = [
            # TODO: Update Multiaddr package to accept quic-v1
            Multiaddr(
                f"/ip4/127.0.0.1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_DRAFT29}"
            ),
            Multiaddr(
                f"/ip4/192.168.1.1/udp/8080/{QUICTransportConfig.PROTOCOL_QUIC_DRAFT29}"
            ),
            Multiaddr(
                f"/ip6/::1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_DRAFT29}"
            ),
            Multiaddr(
                f"/ip4/127.0.0.1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_V1}"
            ),
            Multiaddr(
                f"/ip4/192.168.1.1/udp/8080/{QUICTransportConfig.PROTOCOL_QUIC_V1}"
            ),
            Multiaddr(
                f"/ip6/::1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_V1}"
            ),
        ]

        for addr in valid:
            assert is_quic_multiaddr(addr)

        # Invalid multiaddrs
        invalid = [
            Multiaddr("/ip4/127.0.0.1/tcp/4001"),
            Multiaddr("/ip4/127.0.0.1/udp/4001"),
            Multiaddr("/ip4/127.0.0.1/udp/4001/ws"),
        ]

        for addr in invalid:
            assert not is_quic_multiaddr(addr)

    def test_quic_multiaddr_to_endpoint(self):
        """Test multiaddr to endpoint conversion."""
        addr = Multiaddr("/ip4/192.168.1.100/udp/4001/quic")
        host, port = quic_multiaddr_to_endpoint(addr)

        assert host == "192.168.1.100"
        assert port == 4001

        # Test IPv6
        # TODO: Update Multiaddr project to handle ip6
        # addr6 = Multiaddr("/ip6/::1/udp/8080/quic")
        # host6, port6 = quic_multiaddr_to_endpoint(addr6)

        # assert host6 == "::1"
        # assert port6 == 8080

    def test_create_quic_multiaddr(self):
        """Test QUIC multiaddr creation."""
        # IPv4
        addr = create_quic_multiaddr("127.0.0.1", 4001, "/quic")
        assert str(addr) == "/ip4/127.0.0.1/udp/4001/quic"

        # IPv6
        addr6 = create_quic_multiaddr("::1", 8080, "/quic")
        assert str(addr6) == "/ip6/::1/udp/8080/quic"

    def test_multiaddr_to_quic_version(self):
        """Test QUIC version extraction."""
        addr = Multiaddr("/ip4/127.0.0.1/udp/4001/quic")
        version = multiaddr_to_quic_version(addr)
        assert version in ["quic", "quic-v1"]  # Depending on implementation

    def test_invalid_multiaddr_operations(self):
        """Test error handling for invalid multiaddrs."""
        invalid_addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

        with pytest.raises(ValueError):
            quic_multiaddr_to_endpoint(invalid_addr)

        with pytest.raises(ValueError):
            multiaddr_to_quic_version(invalid_addr)

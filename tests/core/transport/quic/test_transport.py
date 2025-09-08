from unittest.mock import (
    Mock,
)

import pytest

from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.crypto.keys import PrivateKey
from libp2p.transport.quic.exceptions import (
    QUICDialError,
    QUICListenError,
)
from libp2p.transport.quic.transport import (
    QUICTransport,
    QUICTransportConfig,
)


class TestQUICTransport:
    """Test suite for QUIC transport using trio."""

    @pytest.fixture
    def private_key(self):
        """Generate test private key."""
        return create_new_key_pair().private_key

    @pytest.fixture
    def transport_config(self):
        """Generate test transport configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0, enable_draft29=True, enable_v1=True
        )

    @pytest.fixture
    def transport(self, private_key: PrivateKey, transport_config: QUICTransportConfig):
        """Create test transport instance."""
        return QUICTransport(private_key, transport_config)

    def test_transport_initialization(self, transport):
        """Test transport initialization."""
        assert transport._private_key is not None
        assert transport._peer_id is not None
        assert not transport._closed
        assert len(transport._quic_configs) >= 1

    def test_supported_protocols(self, transport):
        """Test supported protocol identifiers."""
        protocols = transport.protocols()
        # TODO: Update when quic-v1 compatible
        # assert "quic-v1" in protocols
        assert "quic" in protocols  # draft-29

    def test_can_dial_quic_addresses(self, transport: QUICTransport):
        """Test multiaddr compatibility checking."""
        import multiaddr

        # Valid QUIC addresses
        valid_addrs = [
            # TODO: Update Multiaddr package to accept quic-v1
            multiaddr.Multiaddr(
                f"/ip4/127.0.0.1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_DRAFT29}"
            ),
            multiaddr.Multiaddr(
                f"/ip4/192.168.1.1/udp/8080/{QUICTransportConfig.PROTOCOL_QUIC_DRAFT29}"
            ),
            multiaddr.Multiaddr(
                f"/ip6/::1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_DRAFT29}"
            ),
            multiaddr.Multiaddr(
                f"/ip4/127.0.0.1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_V1}"
            ),
            multiaddr.Multiaddr(
                f"/ip4/192.168.1.1/udp/8080/{QUICTransportConfig.PROTOCOL_QUIC_V1}"
            ),
            multiaddr.Multiaddr(
                f"/ip6/::1/udp/4001/{QUICTransportConfig.PROTOCOL_QUIC_V1}"
            ),
        ]

        for addr in valid_addrs:
            assert transport.can_dial(addr)

        # Invalid addresses
        invalid_addrs = [
            multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/4001"),
            multiaddr.Multiaddr("/ip4/127.0.0.1/udp/4001"),
            multiaddr.Multiaddr("/ip4/127.0.0.1/udp/4001/ws"),
        ]

        for addr in invalid_addrs:
            assert not transport.can_dial(addr)

    @pytest.mark.trio
    async def test_transport_lifecycle(self, transport):
        """Test transport lifecycle management using trio."""
        assert not transport._closed

        await transport.close()
        assert transport._closed

        # Should be safe to close multiple times
        await transport.close()

    @pytest.mark.trio
    async def test_dial_closed_transport(self, transport: QUICTransport) -> None:
        """Test dialing with closed transport raises error."""
        import multiaddr

        await transport.close()

        with pytest.raises(QUICDialError, match="Transport is closed"):
            await transport.dial(
                multiaddr.Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            )

    def test_create_listener_closed_transport(self, transport: QUICTransport) -> None:
        """Test creating listener with closed transport raises error."""
        transport._closed = True

        with pytest.raises(QUICListenError, match="Transport is closed"):
            transport.create_listener(Mock())

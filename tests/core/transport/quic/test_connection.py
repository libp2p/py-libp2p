from unittest.mock import (
    Mock,
)

import pytest
from multiaddr.multiaddr import Multiaddr

from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.peer.id import ID
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.exceptions import QUICStreamError


class TestQUICConnection:
    """Test suite for QUIC connection functionality."""

    @pytest.fixture
    def mock_quic_connection(self):
        """Create mock aioquic QuicConnection."""
        mock = Mock()
        mock.next_event.return_value = None
        mock.datagrams_to_send.return_value = []
        mock.get_timer.return_value = None
        return mock

    @pytest.fixture
    def quic_connection(self, mock_quic_connection):
        """Create test QUIC connection."""
        private_key = create_new_key_pair().private_key
        peer_id = ID.from_pubkey(private_key.get_public_key())

        return QUICConnection(
            quic_connection=mock_quic_connection,
            remote_addr=("127.0.0.1", 4001),
            peer_id=peer_id,
            local_peer_id=peer_id,
            is_initiator=True,
            maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            transport=Mock(),
        )

    def test_connection_initialization(self, quic_connection):
        """Test connection initialization."""
        assert quic_connection._remote_addr == ("127.0.0.1", 4001)
        assert quic_connection.is_initiator is True
        assert not quic_connection.is_closed
        assert not quic_connection.is_established
        assert len(quic_connection._streams) == 0

    def test_stream_id_calculation(self):
        """Test stream ID calculation for client/server."""
        # Client connection (initiator)
        client_conn = QUICConnection(
            quic_connection=Mock(),
            remote_addr=("127.0.0.1", 4001),
            peer_id=None,
            local_peer_id=Mock(),
            is_initiator=True,
            maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            transport=Mock(),
        )
        assert client_conn._next_stream_id == 0  # Client starts with 0

        # Server connection (not initiator)
        server_conn = QUICConnection(
            quic_connection=Mock(),
            remote_addr=("127.0.0.1", 4001),
            peer_id=None,
            local_peer_id=Mock(),
            is_initiator=False,
            maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            transport=Mock(),
        )
        assert server_conn._next_stream_id == 1  # Server starts with 1

    def test_incoming_stream_detection(self, quic_connection):
        """Test incoming stream detection logic."""
        # For client (initiator), odd stream IDs are incoming
        assert quic_connection._is_incoming_stream(1) is True  # Server-initiated
        assert quic_connection._is_incoming_stream(0) is False  # Client-initiated
        assert quic_connection._is_incoming_stream(5) is True  # Server-initiated
        assert quic_connection._is_incoming_stream(4) is False  # Client-initiated

    @pytest.mark.trio
    async def test_connection_stats(self, quic_connection):
        """Test connection statistics."""
        stats = quic_connection.get_stats()

        expected_keys = [
            "peer_id",
            "remote_addr",
            "is_initiator",
            "is_established",
            "is_closed",
            "active_streams",
            "next_stream_id",
        ]

        for key in expected_keys:
            assert key in stats

    @pytest.mark.trio
    async def test_connection_close(self, quic_connection):
        """Test connection close functionality."""
        assert not quic_connection.is_closed

        await quic_connection.close()

        assert quic_connection.is_closed

    @pytest.mark.trio
    async def test_stream_operations_on_closed_connection(self, quic_connection):
        """Test stream operations on closed connection."""
        await quic_connection.close()

        with pytest.raises(QUICStreamError, match="Connection is closed"):
            await quic_connection.open_stream()

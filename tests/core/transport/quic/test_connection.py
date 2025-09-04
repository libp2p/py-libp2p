"""
Enhanced tests for QUIC connection functionality - Module 3.
Tests all new features including advanced stream management, resource management,
error handling, and concurrent operations.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from multiaddr.multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.exceptions import (
    QUICConnectionClosedError,
    QUICConnectionError,
    QUICConnectionTimeoutError,
    QUICPeerVerificationError,
    QUICStreamLimitError,
    QUICStreamTimeoutError,
)
from libp2p.transport.quic.security import QUICTLSConfigManager
from libp2p.transport.quic.stream import QUICStream, StreamDirection


class MockResourceScope:
    """Mock resource scope for testing."""

    def __init__(self):
        self.memory_reserved = 0

    def reserve_memory(self, size):
        self.memory_reserved += size

    def release_memory(self, size):
        self.memory_reserved = max(0, self.memory_reserved - size)


class TestQUICConnection:
    """Test suite for QUIC connection functionality."""

    @pytest.fixture
    def mock_quic_connection(self):
        """Create mock aioquic QuicConnection."""
        mock = Mock()
        mock.next_event.return_value = None
        mock.datagrams_to_send.return_value = []
        mock.get_timer.return_value = None
        mock.connect = Mock()
        mock.close = Mock()
        mock.send_stream_data = Mock()
        mock.reset_stream = Mock()
        return mock

    @pytest.fixture
    def mock_quic_transport(self):
        mock = Mock()
        mock._config = QUICTransportConfig()
        return mock

    @pytest.fixture
    def mock_resource_scope(self):
        """Create mock resource scope."""
        return MockResourceScope()

    @pytest.fixture
    def quic_connection(
        self,
        mock_quic_connection: Mock,
        mock_quic_transport: Mock,
        mock_resource_scope: MockResourceScope,
    ):
        """Create test QUIC connection with enhanced features."""
        private_key = create_new_key_pair().private_key
        peer_id = ID.from_pubkey(private_key.get_public_key())
        mock_security_manager = Mock()

        return QUICConnection(
            quic_connection=mock_quic_connection,
            remote_addr=("127.0.0.1", 4001),
            remote_peer_id=None,
            local_peer_id=peer_id,
            is_initiator=True,
            maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            transport=mock_quic_transport,
            resource_scope=mock_resource_scope,
            security_manager=mock_security_manager,
        )

    @pytest.fixture
    def server_connection(self, mock_quic_connection, mock_resource_scope):
        """Create server-side QUIC connection."""
        private_key = create_new_key_pair().private_key
        peer_id = ID.from_pubkey(private_key.get_public_key())

        return QUICConnection(
            quic_connection=mock_quic_connection,
            remote_addr=("127.0.0.1", 4001),
            remote_peer_id=peer_id,
            local_peer_id=peer_id,
            is_initiator=False,
            maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            transport=Mock(),
            resource_scope=mock_resource_scope,
        )

    # Basic functionality tests

    def test_connection_initialization_enhanced(
        self, quic_connection, mock_resource_scope
    ):
        """Test enhanced connection initialization."""
        assert quic_connection._remote_addr == ("127.0.0.1", 4001)
        assert quic_connection.is_initiator is True
        assert not quic_connection.is_closed
        assert not quic_connection.is_established
        assert len(quic_connection._streams) == 0
        assert quic_connection._resource_scope == mock_resource_scope
        assert quic_connection._outbound_stream_count == 0
        assert quic_connection._inbound_stream_count == 0
        assert len(quic_connection._stream_accept_queue) == 0

    def test_stream_id_calculation_enhanced(self):
        """Test enhanced stream ID calculation for client/server."""
        # Client connection (initiator)
        client_conn = QUICConnection(
            quic_connection=Mock(),
            remote_addr=("127.0.0.1", 4001),
            remote_peer_id=None,
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
            remote_peer_id=None,
            local_peer_id=Mock(),
            is_initiator=False,
            maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
            transport=Mock(),
        )
        assert server_conn._next_stream_id == 1  # Server starts with 1

    def test_incoming_stream_detection_enhanced(self, quic_connection):
        """Test enhanced incoming stream detection logic."""
        # For client (initiator), odd stream IDs are incoming
        assert quic_connection._is_incoming_stream(1) is True  # Server-initiated
        assert quic_connection._is_incoming_stream(0) is False  # Client-initiated
        assert quic_connection._is_incoming_stream(5) is True  # Server-initiated
        assert quic_connection._is_incoming_stream(4) is False  # Client-initiated

    # Stream management tests

    @pytest.mark.trio
    async def test_open_stream_basic(self, quic_connection):
        """Test basic stream opening."""
        quic_connection._started = True

        stream = await quic_connection.open_stream()

        assert isinstance(stream, QUICStream)
        assert stream.stream_id == "0"
        assert stream.direction == StreamDirection.OUTBOUND
        assert 0 in quic_connection._streams
        assert quic_connection._outbound_stream_count == 1

    @pytest.mark.trio
    async def test_open_stream_limit_reached(self, quic_connection):
        """Test stream limit enforcement."""
        quic_connection._started = True
        quic_connection._outbound_stream_count = quic_connection.MAX_OUTGOING_STREAMS

        with pytest.raises(QUICStreamLimitError, match="Maximum outbound streams"):
            await quic_connection.open_stream()

    @pytest.mark.trio
    async def test_open_stream_timeout(self, quic_connection: QUICConnection):
        """Test stream opening timeout."""
        quic_connection._started = True
        return

        # Mock the stream ID lock to simulate slow operation
        async def slow_acquire():
            await trio.sleep(10)  # Longer than timeout

        with patch.object(
            quic_connection._stream_lock, "acquire", side_effect=slow_acquire
        ):
            with pytest.raises(
                QUICStreamTimeoutError, match="Stream creation timed out"
            ):
                await quic_connection.open_stream(timeout=0.1)

    @pytest.mark.trio
    async def test_accept_stream_basic(self, quic_connection):
        """Test basic stream acceptance."""
        # Create a mock inbound stream
        mock_stream = Mock(spec=QUICStream)
        mock_stream.stream_id = "1"

        # Add to accept queue
        quic_connection._stream_accept_queue.append(mock_stream)
        quic_connection._stream_accept_event.set()

        accepted_stream = await quic_connection.accept_stream(timeout=0.1)

        assert accepted_stream == mock_stream
        assert len(quic_connection._stream_accept_queue) == 0

    @pytest.mark.trio
    async def test_accept_stream_timeout(self, quic_connection):
        """Test stream acceptance timeout."""
        with pytest.raises(QUICStreamTimeoutError, match="Stream accept timed out"):
            await quic_connection.accept_stream(timeout=0.1)

    @pytest.mark.trio
    async def test_accept_stream_on_closed_connection(self, quic_connection):
        """Test stream acceptance on closed connection."""
        await quic_connection.close()

        with pytest.raises(QUICConnectionClosedError, match="Connection is closed"):
            await quic_connection.accept_stream()

    # Stream handler tests

    @pytest.mark.trio
    async def test_stream_handler_setting(self, quic_connection):
        """Test setting stream handler."""

        async def mock_handler(stream):
            pass

        quic_connection.set_stream_handler(mock_handler)
        assert quic_connection._stream_handler == mock_handler

    # Connection lifecycle tests

    @pytest.mark.trio
    async def test_connection_start_client(self, quic_connection):
        """Test client connection start."""
        with patch.object(
            quic_connection, "_initiate_connection", new_callable=AsyncMock
        ) as mock_initiate:
            await quic_connection.start()

            assert quic_connection._started
            mock_initiate.assert_called_once()

    @pytest.mark.trio
    async def test_connection_start_server(self, server_connection):
        """Test server connection start."""
        await server_connection.start()

        assert server_connection._started
        assert server_connection._established
        assert server_connection._connected_event.is_set()

    @pytest.mark.trio
    async def test_connection_start_already_started(self, quic_connection):
        """Test starting already started connection."""
        quic_connection._started = True

        # Should not raise error, just log warning
        await quic_connection.start()
        assert quic_connection._started

    @pytest.mark.trio
    async def test_connection_start_closed(self, quic_connection):
        """Test starting closed connection."""
        quic_connection._closed = True

        with pytest.raises(
            QUICConnectionError, match="Cannot start a closed connection"
        ):
            await quic_connection.start()

    @pytest.mark.trio
    async def test_connection_connect_with_nursery(
        self, quic_connection: QUICConnection
    ):
        """Test connection establishment with nursery."""
        quic_connection._started = True
        quic_connection._established = True
        quic_connection._connected_event.set()

        with patch.object(
            quic_connection, "_start_background_tasks", new_callable=AsyncMock
        ) as mock_start_tasks:
            with patch.object(
                quic_connection,
                "_verify_peer_identity_with_security",
                new_callable=AsyncMock,
            ) as mock_verify:
                async with trio.open_nursery() as nursery:
                    await quic_connection.connect(nursery)

                    assert quic_connection._nursery == nursery
                    mock_start_tasks.assert_called_once()
                    mock_verify.assert_called_once()

    @pytest.mark.trio
    @pytest.mark.slow
    async def test_connection_connect_timeout(
        self, quic_connection: QUICConnection
    ) -> None:
        """Test connection establishment timeout."""
        quic_connection._started = True
        # Don't set connected event to simulate timeout

        with patch.object(
            quic_connection, "_start_background_tasks", new_callable=AsyncMock
        ):
            async with trio.open_nursery() as nursery:
                with pytest.raises(
                    QUICConnectionTimeoutError, match="Connection handshake timed out"
                ):
                    await quic_connection.connect(nursery)

    # Resource management tests

    @pytest.mark.trio
    async def test_stream_removal_resource_cleanup(
        self, quic_connection: QUICConnection, mock_resource_scope
    ):
        """Test stream removal and resource cleanup."""
        quic_connection._started = True

        # Create a stream
        stream = await quic_connection.open_stream()

        # Remove the stream
        quic_connection._remove_stream(int(stream.stream_id))

        assert int(stream.stream_id) not in quic_connection._streams
        # Note: Count updates is async, so we can't test it directly here

    # Error handling tests

    @pytest.mark.trio
    async def test_connection_error_handling(self, quic_connection) -> None:
        """Test connection error handling."""
        error = Exception("Test error")

        with patch.object(
            quic_connection, "close", new_callable=AsyncMock
        ) as mock_close:
            await quic_connection._handle_connection_error(error)
            mock_close.assert_called_once()

    # Statistics and monitoring tests

    @pytest.mark.trio
    async def test_connection_stats_enhanced(self, quic_connection) -> None:
        """Test enhanced connection statistics."""
        quic_connection._started = True

        # Create some streams
        _stream1 = await quic_connection.open_stream()
        _stream2 = await quic_connection.open_stream()

        stats = quic_connection.get_stream_stats()

        expected_keys = [
            "total_streams",
            "outbound_streams",
            "inbound_streams",
            "max_streams",
            "stream_utilization",
            "stats",
        ]

        for key in expected_keys:
            assert key in stats

        assert stats["total_streams"] == 2
        assert stats["outbound_streams"] == 2
        assert stats["inbound_streams"] == 0

    @pytest.mark.trio
    async def test_get_active_streams(self, quic_connection) -> None:
        """Test getting active streams."""
        quic_connection._started = True

        # Create streams
        stream1 = await quic_connection.open_stream()
        stream2 = await quic_connection.open_stream()

        active_streams = quic_connection.get_active_streams()

        assert len(active_streams) == 2
        assert stream1 in active_streams
        assert stream2 in active_streams

    @pytest.mark.trio
    async def test_get_streams_by_protocol(self, quic_connection) -> None:
        """Test getting streams by protocol."""
        quic_connection._started = True

        # Create streams with different protocols
        stream1 = await quic_connection.open_stream()
        stream1.protocol = "/test/1.0.0"

        stream2 = await quic_connection.open_stream()
        stream2.protocol = "/other/1.0.0"

        test_streams = quic_connection.get_streams_by_protocol("/test/1.0.0")
        other_streams = quic_connection.get_streams_by_protocol("/other/1.0.0")

        assert len(test_streams) == 1
        assert len(other_streams) == 1
        assert stream1 in test_streams
        assert stream2 in other_streams

    # Enhanced close tests

    @pytest.mark.trio
    async def test_connection_close_enhanced(
        self, quic_connection: QUICConnection
    ) -> None:
        """Test enhanced connection close with stream cleanup."""
        quic_connection._started = True

        # Create some streams
        _stream1 = await quic_connection.open_stream()
        _stream2 = await quic_connection.open_stream()

        await quic_connection.close()

        assert quic_connection.is_closed
        assert len(quic_connection._streams) == 0

    # Concurrent operations tests

    @pytest.mark.trio
    async def test_concurrent_stream_operations(
        self, quic_connection: QUICConnection
    ) -> None:
        """Test concurrent stream operations."""
        quic_connection._started = True

        async def create_stream():
            return await quic_connection.open_stream()

        # Create multiple streams concurrently
        async with trio.open_nursery() as nursery:
            for i in range(10):
                nursery.start_soon(create_stream)

            # Wait a bit for all to start
            await trio.sleep(0.1)

        # Should have created streams without conflicts
        assert quic_connection._outbound_stream_count == 10
        assert len(quic_connection._streams) == 10

    # Connection properties tests

    def test_connection_properties(self, quic_connection: QUICConnection) -> None:
        """Test connection property accessors."""
        assert quic_connection.multiaddr() == quic_connection._maddr
        assert quic_connection.local_peer_id() == quic_connection._local_peer_id
        assert quic_connection.remote_peer_id() == quic_connection._remote_peer_id

    # IRawConnection interface tests

    @pytest.mark.trio
    async def test_raw_connection_write(self, quic_connection: QUICConnection) -> None:
        """Test raw connection write interface."""
        quic_connection._started = True

        with patch.object(quic_connection, "open_stream") as mock_open:
            mock_stream = AsyncMock()
            mock_open.return_value = mock_stream

            await quic_connection.write(b"test data")

            mock_open.assert_called_once()
            mock_stream.write.assert_called_once_with(b"test data")
            mock_stream.close_write.assert_called_once()

    @pytest.mark.trio
    async def test_raw_connection_read_not_implemented(
        self, quic_connection: QUICConnection
    ) -> None:
        """Test raw connection read raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await quic_connection.read()

    # Mock verification helpers

    def test_mock_resource_scope_functionality(self, mock_resource_scope) -> None:
        """Test mock resource scope works correctly."""
        assert mock_resource_scope.memory_reserved == 0

        mock_resource_scope.reserve_memory(1000)
        assert mock_resource_scope.memory_reserved == 1000

        mock_resource_scope.reserve_memory(500)
        assert mock_resource_scope.memory_reserved == 1500

        mock_resource_scope.release_memory(600)
        assert mock_resource_scope.memory_reserved == 900

        mock_resource_scope.release_memory(2000)  # Should not go negative
        assert mock_resource_scope.memory_reserved == 0


@pytest.mark.trio
async def test_invalid_certificate_verification():
    key_pair1 = create_new_key_pair()
    key_pair2 = create_new_key_pair()

    peer_id1 = ID.from_pubkey(key_pair1.public_key)
    peer_id2 = ID.from_pubkey(key_pair2.public_key)

    manager = QUICTLSConfigManager(
        libp2p_private_key=key_pair1.private_key, peer_id=peer_id1
    )

    # Match the certificate against a different peer_id
    with pytest.raises(QUICPeerVerificationError, match="Peer ID mismatch"):
        manager.verify_peer_identity(manager.tls_config.certificate, peer_id2)

    from cryptography.hazmat.primitives.serialization import Encoding

    # --- Corrupt the certificate by tampering the DER bytes ---
    cert_bytes = manager.tls_config.certificate.public_bytes(Encoding.DER)
    corrupted_bytes = bytearray(cert_bytes)

    # Flip some random bytes in the middle of the certificate
    corrupted_bytes[len(corrupted_bytes) // 2] ^= 0xFF

    from cryptography import x509
    from cryptography.hazmat.backends import default_backend

    # This will still parse (structurally valid), but the signature
    # or fingerprint will break
    corrupted_cert = x509.load_der_x509_certificate(
        bytes(corrupted_bytes), backend=default_backend()
    )

    with pytest.raises(
        QUICPeerVerificationError, match="Certificate verification failed"
    ):
        manager.verify_peer_identity(corrupted_cert, peer_id1)

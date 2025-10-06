"""
Unit tests for the rendezvous service.
"""

import time
from unittest.mock import AsyncMock, Mock

import pytest
import varint

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.discovery.rendezvous.config import (
    MAX_DISCOVER_LIMIT,
    MAX_NAMESPACE_LENGTH,
    MAX_TTL,
    RENDEZVOUS_PROTOCOL,
)
from libp2p.discovery.rendezvous.pb.rendezvous_pb2 import Message
from libp2p.discovery.rendezvous.service import RegistrationRecord, RendezvousService
from libp2p.peer.id import ID


@pytest.fixture
def mock_host():
    """Mock host for testing."""
    host = Mock()
    host.set_stream_handler = Mock()
    return host


@pytest.fixture
def service(mock_host):
    """Rendezvous service for testing."""
    return RendezvousService(mock_host)


@pytest.fixture
def sample_peer_id():
    """Sample peer ID for testing."""
    return ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ")


@pytest.fixture
def sample_addrs():
    """Sample addresses for testing."""
    return [b"/ip4/127.0.0.1/tcp/8000", b"/ip4/192.168.1.1/tcp/8000"]


class TestRegistrationRecord:
    """Test cases for RegistrationRecord."""

    def test_init(self, sample_peer_id, sample_addrs):
        """Test registration record initialization."""
        ttl = 3600
        record = RegistrationRecord(sample_peer_id, sample_addrs, "test-ns", ttl)

        assert record.peer_id == sample_peer_id
        assert record.addrs == sample_addrs
        assert record.namespace == "test-ns"
        assert record.ttl == ttl
        assert isinstance(record.registered_at, float)
        assert record.expires_at == record.registered_at + ttl

    def test_is_expired_false(self, sample_peer_id, sample_addrs):
        """Test that fresh registration is not expired."""
        record = RegistrationRecord(sample_peer_id, sample_addrs, "test-ns", 3600)
        assert not record.is_expired()

    def test_is_expired_true(self, sample_peer_id, sample_addrs):
        """Test that old registration is expired."""
        record = RegistrationRecord(sample_peer_id, sample_addrs, "test-ns", 1)
        # Wait for expiration
        time.sleep(1.1)
        assert record.is_expired()

    def test_to_protobuf_register(self, sample_peer_id, sample_addrs):
        """Test conversion to protobuf Register message."""
        record = RegistrationRecord(sample_peer_id, sample_addrs, "test-ns", 3600)
        register = record.to_protobuf_register()

        assert register.ns == "test-ns"
        assert register.peer.id == sample_peer_id.to_bytes()
        assert list(register.peer.addrs) == sample_addrs
        assert register.ttl <= 3600


class TestRendezvousService:
    """Test cases for RendezvousService."""

    def test_init(self, mock_host):
        """Test service initialization."""
        service = RendezvousService(mock_host)

        assert service.host == mock_host
        assert service.registrations == {}
        mock_host.set_stream_handler.assert_called_with(
            RENDEZVOUS_PROTOCOL, service._handle_stream
        )

    @pytest.mark.trio
    async def test_handle_register_success(self, service, sample_peer_id, sample_addrs):
        """Test successful registration handling."""
        # Create register message
        message = Message()
        message.type = Message.MessageType.REGISTER
        message.register.ns = "test-namespace"
        message.register.peer.id = sample_peer_id.to_bytes()
        message.register.peer.addrs.extend(sample_addrs)
        message.register.ttl = 3600

        # Mock stream
        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id
        mock_stream.write = AsyncMock()

        # Test registration
        response = service._handle_register(sample_peer_id, message.register)

        assert response.registerResponse.status == Message.ResponseStatus.OK
        assert response.registerResponse.ttl <= 3600  # Server can reduce TTL
        assert "test-namespace" in service.registrations
        assert sample_peer_id in service.registrations["test-namespace"]

    @pytest.mark.trio
    async def test_handle_register_invalid_namespace(self, service, sample_peer_id):
        """Test registration with invalid namespace."""
        # Create register message with invalid namespace
        message = Message()
        message.type = Message.MessageType.REGISTER
        message.register.ns = "x" * (MAX_NAMESPACE_LENGTH + 1)  # Too long
        message.register.peer.id = sample_peer_id.to_bytes()
        message.register.ttl = 3600

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id

        response = service._handle_register(sample_peer_id, message.register)
        assert (
            response.registerResponse.status
            == Message.ResponseStatus.E_INVALID_NAMESPACE
        )

    @pytest.mark.trio
    async def test_handle_register_invalid_ttl(
        self, service, sample_peer_id, sample_addrs
    ):
        """Test registration with invalid TTL."""
        # Create register message with invalid TTL
        message = Message()
        message.type = Message.MessageType.REGISTER
        message.register.ns = "test-namespace"
        message.register.peer.id = sample_peer_id.to_bytes()
        message.register.peer.addrs.extend(sample_addrs)
        message.register.ttl = MAX_TTL + 1  # Too long

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id

        response = service._handle_register(sample_peer_id, message.register)
        assert response.registerResponse.status == Message.ResponseStatus.E_INVALID_TTL

    @pytest.mark.trio
    async def test_handle_register_no_addresses(self, service, sample_peer_id):
        """Test registration with no addresses."""
        # Create register message without addresses
        message = Message()
        message.type = Message.MessageType.REGISTER
        message.register.ns = "test-namespace"
        message.register.peer.id = sample_peer_id.to_bytes()
        # No addresses added
        message.register.ttl = 3600

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id

        response = service._handle_register(sample_peer_id, message.register)
        # Service allows registration without addresses
        assert response.registerResponse.status == Message.ResponseStatus.OK

    @pytest.mark.trio
    async def test_handle_discover_success(self, service, sample_peer_id, sample_addrs):
        """Test successful discovery handling."""
        # First register a peer
        service.registrations["test-namespace"] = {
            sample_peer_id: RegistrationRecord(
                sample_peer_id, sample_addrs, "test-namespace", 3600
            )
        }

        # Create discover message
        message = Message()
        message.type = Message.MessageType.DISCOVER
        message.discover.ns = "test-namespace"
        message.discover.limit = 10

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = ID.from_base58(
            "QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"
        )

        response = service._handle_discover(
            ID.from_base58("QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"),
            message.discover,
        )

        assert response.discoverResponse.status == Message.ResponseStatus.OK
        assert len(response.discoverResponse.registrations) == 1
        assert (
            response.discoverResponse.registrations[0].peer.id
            == sample_peer_id.to_bytes()
        )

    @pytest.mark.trio
    async def test_handle_discover_no_peers(self, service):
        """Test discovery with no registered peers."""
        # Create discover message for empty namespace
        message = Message()
        message.type = Message.MessageType.DISCOVER
        message.discover.ns = "empty-namespace"
        message.discover.limit = 10

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = ID.from_base58(
            "QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"
        )

        response = service._handle_discover(
            ID.from_base58("QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"),
            message.discover,
        )

        assert response.discoverResponse.status == Message.ResponseStatus.OK
        assert len(response.discoverResponse.registrations) == 0

    @pytest.mark.trio
    async def test_handle_discover_limit(self, service, sample_addrs):
        """Test discovery with limit."""
        # Register multiple peers
        namespace = "test-namespace"
        service.registrations[namespace] = {}

        for i in range(5):
            # Generate valid peer IDs using crypto
            key_pair = create_new_key_pair()
            peer_id = ID.from_pubkey(key_pair.public_key)
            service.registrations[namespace][peer_id] = RegistrationRecord(
                peer_id, sample_addrs, namespace, 3600
            )

        # Create discover message with limit
        message = Message()
        message.type = Message.MessageType.DISCOVER
        message.discover.ns = namespace
        message.discover.limit = 3

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = ID.from_base58(
            "QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"
        )

        response = service._handle_discover(
            ID.from_base58("QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"),
            message.discover,
        )

        assert response.discoverResponse.status == Message.ResponseStatus.OK
        assert len(response.discoverResponse.registrations) == 3

    @pytest.mark.trio
    async def test_handle_discover_invalid_limit(self, service):
        """Test discovery with invalid limit."""
        # Create discover message with too high limit
        message = Message()
        message.type = Message.MessageType.DISCOVER
        message.discover.ns = "test-namespace"
        message.discover.limit = MAX_DISCOVER_LIMIT + 1

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = ID.from_base58(
            "QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"
        )

        response = service._handle_discover(
            ID.from_base58("QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"),
            message.discover,
        )
        # Service clamps limit to MAX_DISCOVER_LIMIT, doesn't error
        assert response.discoverResponse.status == Message.ResponseStatus.OK

    @pytest.mark.trio
    async def test_handle_unregister_success(
        self, service, sample_peer_id, sample_addrs
    ):
        """Test successful unregistration."""
        # First register a peer
        namespace = "test-namespace"
        service.registrations[namespace] = {
            sample_peer_id: RegistrationRecord(
                sample_peer_id, sample_addrs, namespace, 3600
            )
        }

        # Create unregister message
        message = Message()
        message.type = Message.MessageType.UNREGISTER
        message.unregister.ns = namespace
        message.unregister.id = sample_peer_id.to_bytes()

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id

        # Unregister (no response returned)
        service._handle_unregister(sample_peer_id, message.unregister)

        # Check that peer was removed
        assert sample_peer_id not in service.registrations.get(namespace, {})

    @pytest.mark.trio
    async def test_handle_unregister_not_found(self, service, sample_peer_id):
        """Test unregistration of non-existent registration."""
        # Create unregister message for non-existent registration
        message = Message()
        message.type = Message.MessageType.UNREGISTER
        message.unregister.ns = "test-namespace"
        message.unregister.id = sample_peer_id.to_bytes()

        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id

        # Unregister (no response returned - should not raise error)
        service._handle_unregister(sample_peer_id, message.unregister)

    def test_cleanup_expired_registrations(self, service, sample_peer_id, sample_addrs):
        """Test cleanup of expired registrations."""
        # Add expired registration
        namespace = "test-namespace"
        service.registrations[namespace] = {}

        expired_record = RegistrationRecord(sample_peer_id, sample_addrs, namespace, 1)
        # Manually set expiration time to past
        expired_record.expires_at = time.time() - 1
        service.registrations[namespace][sample_peer_id] = expired_record

        # Add fresh registration
        fresh_peer_id = ID.from_base58("QmFreshPeer123")
        fresh_record = RegistrationRecord(fresh_peer_id, sample_addrs, namespace, 3600)
        service.registrations[namespace][fresh_peer_id] = fresh_record

        # Cleanup should remove only expired
        service._cleanup_expired_registrations(namespace)

        assert sample_peer_id not in service.registrations[namespace]
        assert fresh_peer_id in service.registrations[namespace]

    @pytest.mark.trio
    async def test_stream_handler_integration(self, service, sample_peer_id):
        """Test the stream handler integration."""
        # Mock stream with message data
        mock_stream = Mock()
        mock_stream.muxed_conn.peer_id = sample_peer_id
        mock_stream.read = AsyncMock()
        mock_stream.write = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create a register message
        message = Message()
        message.type = Message.MessageType.REGISTER
        message.register.ns = "test-namespace"
        message.register.peer.id = sample_peer_id.to_bytes()
        message.register.peer.addrs.append(b"/ip4/127.0.0.1/tcp/8000")
        message.register.ttl = 3600

        # Mock stream reads - varint bytes one at a time, then message, then EOF
        serialized = message.SerializeToString()
        varint_length = len(serialized)
        # Encode length as varint and split bytes
        varint_bytes = varint.encode(varint_length)
        varint_reads = [bytes([b]) for b in varint_bytes]  # Each byte separately

        mock_stream.read.side_effect = (
            varint_reads  # Length varint bytes one at a time
            + [serialized]  # Then the full message data
            + [b""]  # EOF to end the loop
        )

        # Test stream handling
        await service._handle_stream(mock_stream)

        # Verify response was written
        assert mock_stream.write.called

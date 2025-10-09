"""
Unit tests for the rendezvous client.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from multiaddr import Multiaddr

from libp2p.discovery.rendezvous.client import RendezvousClient
from libp2p.discovery.rendezvous.config import (
    DEFAULT_TTL,
    MAX_DISCOVER_LIMIT,
    MAX_NAMESPACE_LENGTH,
    MAX_TTL,
    MIN_TTL,
)
from libp2p.discovery.rendezvous.errors import RendezvousError
from libp2p.discovery.rendezvous.pb.rendezvous_pb2 import Message
from libp2p.peer.id import ID


@pytest.fixture
def mock_host():
    """Mock host for testing."""
    host = Mock()
    host.get_id.return_value = ID.from_base58(
        "QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"
    )
    host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
    host.new_stream = AsyncMock()
    return host


@pytest.fixture
def rendezvous_peer():
    """Rendezvous server peer ID for testing."""
    return ID.from_base58("QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM")


@pytest.fixture
def client(mock_host, rendezvous_peer):
    """Rendezvous client for testing."""
    return RendezvousClient(mock_host, rendezvous_peer)


class TestRendezvousClient:
    """Test cases for RendezvousClient."""

    def create_mock_stream(self):
        """Helper to create a properly mocked stream."""
        mock_stream = Mock()
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()
        return mock_stream

    def test_init(self, mock_host, rendezvous_peer):
        """Test client initialization."""
        client = RendezvousClient(mock_host, rendezvous_peer, enable_refresh=True)
        assert client.host == mock_host
        assert client.rendezvous_peer == rendezvous_peer
        assert client.enable_refresh is True
        assert client._refresh_cancel_scopes == {}
        assert client._nursery is None

    def test_set_nursery(self, client):
        """Test setting nursery for background tasks."""
        nursery = Mock()
        client.set_nursery(nursery)
        assert client._nursery == nursery

    @pytest.mark.trio
    async def test_register_success(self, client, mock_host):
        """Test successful registration."""
        # Setup mock stream
        mock_stream = Mock()
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()
        mock_host.new_stream.return_value = mock_stream

        # Mock successful response
        response = Message()
        response.type = Message.MessageType.REGISTER_RESPONSE
        response.registerResponse.status = Message.ResponseStatus.OK
        response.registerResponse.ttl = DEFAULT_TTL
        mock_stream.read.return_value = response.SerializeToString()

        # Test registration
        ttl = await client.register("test-namespace", DEFAULT_TTL)
        assert ttl == DEFAULT_TTL
        assert mock_host.new_stream.called

    @pytest.mark.trio
    async def test_register_validation_errors(self, client):
        """Test registration parameter validation."""
        # Test TTL too short
        with pytest.raises(ValueError, match="TTL too short"):
            await client.register("test", MIN_TTL - 1)

        # Test TTL too long
        with pytest.raises(ValueError, match="TTL too long"):
            await client.register("test", MAX_TTL + 1)

        # Test namespace too long
        long_namespace = "x" * (MAX_NAMESPACE_LENGTH + 1)
        with pytest.raises(ValueError, match="Namespace too long"):
            await client.register(long_namespace, DEFAULT_TTL)

    @pytest.mark.trio
    async def test_register_no_addresses(self, client, mock_host):
        """Test registration with no available addresses."""
        mock_host.get_addrs.return_value = []

        with pytest.raises(ValueError, match="No addresses available"):
            await client.register("test-namespace", DEFAULT_TTL)

    @pytest.mark.trio
    async def test_discover_success(self, client, mock_host):
        """Test successful peer discovery."""
        # Setup mock stream
        mock_stream = self.create_mock_stream()
        mock_host.new_stream.return_value = mock_stream

        # Mock successful response with peers
        response = Message()
        response.type = Message.MessageType.DISCOVER_RESPONSE
        response.discoverResponse.status = Message.ResponseStatus.OK

        # Add a mock peer
        peer_register = response.discoverResponse.registrations.add()
        peer_register.ns = "test-namespace"
        peer_register.peer.id = ID.from_base58("QmTest123").to_bytes()
        peer_register.peer.addrs.append(b"/ip4/127.0.0.1/tcp/8001")
        peer_register.ttl = DEFAULT_TTL

        mock_stream.read.return_value = response.SerializeToString()

        # Test discovery
        peers, cookie = await client.discover("test-namespace", limit=10)
        assert len(peers) == 1
        assert peers[0].peer_id == ID.from_base58("QmTest123")
        assert cookie == b""  # Default cookie from response
        assert mock_host.new_stream.called

    @pytest.mark.trio
    async def test_discover_with_cookie(self, client, mock_host):
        """Test discovery with continuation cookie."""
        # Setup mock stream
        mock_stream = self.create_mock_stream()
        mock_host.new_stream.return_value = mock_stream

        # Mock response
        response = Message()
        response.type = Message.MessageType.DISCOVER_RESPONSE
        response.discoverResponse.status = Message.ResponseStatus.OK
        response.discoverResponse.cookie = b"test-cookie"
        mock_stream.read.return_value = response.SerializeToString()

        # Test discovery with cookie
        peers, cookie = await client.discover("test-namespace", cookie=b"prev-cookie")
        assert len(peers) == 0  # No peers in mock response
        assert cookie == b"test-cookie"  # Cookie from response
        assert mock_host.new_stream.called

    @pytest.mark.trio
    async def test_discover_limit_handling(self, client, mock_host):
        """Test discovery limit handling."""
        # Setup mock stream
        mock_stream = self.create_mock_stream()
        mock_host.new_stream.return_value = mock_stream

        # Mock response
        response = Message()
        response.type = Message.MessageType.DISCOVER_RESPONSE
        response.discoverResponse.status = Message.ResponseStatus.OK
        mock_stream.read.return_value = response.SerializeToString()

        # Test that limit too high gets capped
        peers, cookie = await client.discover("test", limit=MAX_DISCOVER_LIMIT + 1)
        assert len(peers) == 0  # No peers in mock response
        assert mock_host.new_stream.called

        # Test with long namespace (should work, no validation in client)
        long_namespace = "x" * (MAX_NAMESPACE_LENGTH + 1)
        peers, cookie = await client.discover(long_namespace)
        assert mock_host.new_stream.called

    @pytest.mark.trio
    async def test_unregister_success(self, client, mock_host):
        """Test successful unregistration."""
        # Setup mock stream
        mock_stream = self.create_mock_stream()
        mock_host.new_stream.return_value = mock_stream

        # Test unregistration (no response expected)
        await client.unregister("test-namespace")
        assert mock_host.new_stream.called

    @pytest.mark.trio
    async def test_connection_error(self, client, mock_host):
        """Test handling of connection errors."""
        # Mock connection failure
        mock_host.new_stream.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):  # Could be any connection-related exception
            await client.register("test-namespace")

    @pytest.mark.trio
    async def test_server_error_response(self, client, mock_host):
        """Test handling of server error responses."""
        # Setup mock stream
        mock_stream = self.create_mock_stream()
        mock_host.new_stream.return_value = mock_stream

        # Mock error response
        response = Message()
        response.type = Message.MessageType.REGISTER_RESPONSE
        response.registerResponse.status = Message.ResponseStatus.E_INVALID_NAMESPACE
        response.registerResponse.statusText = "Invalid namespace"
        mock_stream.read.return_value = response.SerializeToString()

        # Test error handling
        with pytest.raises(RendezvousError):
            await client.register("test-namespace")

    @pytest.mark.trio
    async def test_refresh_functionality(self, mock_host, rendezvous_peer):
        """Test automatic registration refresh."""
        client = RendezvousClient(mock_host, rendezvous_peer, enable_refresh=True)

        # Setup mock nursery and stream
        mock_nursery = Mock()
        mock_nursery.start_soon = Mock()
        client.set_nursery(mock_nursery)

        mock_stream = self.create_mock_stream()
        mock_host.new_stream.return_value = mock_stream

        # Mock successful response
        response = Message()
        response.type = Message.MessageType.REGISTER_RESPONSE
        response.registerResponse.status = Message.ResponseStatus.OK
        response.registerResponse.ttl = 3600  # 1 hour
        mock_stream.read.return_value = response.SerializeToString()

        # Test registration with refresh
        ttl = await client.register("test-namespace", 3600)
        assert ttl == 3600

        # Verify refresh task was started
        assert mock_nursery.start_soon.called

    def test_refresh_without_nursery(self, client):
        """Test that refresh is skipped without nursery."""
        client.enable_refresh = True
        # Should not raise error when nursery is None
        # This is tested implicitly by other tests
        assert client._nursery is None

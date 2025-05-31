"""
Unit tests for the Kademlia DHT provider store implementation.

This module contains unit tests for the ProviderStore class.
"""

import logging
import time
from unittest.mock import (
    AsyncMock,
    Mock,
    patch,
)

import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.kad_dht.pb.kademlia_pb2 import (
    Message,
)
from libp2p.kad_dht.provider_store import (
    PROTOCOL_ID,
    PROVIDER_ADDRESS_TTL,
    PROVIDER_RECORD_EXPIRATION_INTERVAL,
    PROVIDER_RECORD_REPUBLISH_INTERVAL,
    ProviderRecord,
    ProviderStore,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

logger = logging.getLogger("test.provider_store")


class TestProviderRecord:
    """Test cases for the ProviderRecord class."""

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = ID(b"provider_peer_id_123456789012345678")
        addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        return PeerInfo(peer_id, addrs)

    def test_provider_record_init(self, sample_peer_info):
        """Test ProviderRecord initialization."""
        record = ProviderRecord(sample_peer_info)

        assert record.provider_info == sample_peer_info
        assert isinstance(record.timestamp, float)
        assert record.timestamp <= time.time()

    def test_provider_record_init_with_timestamp(self, sample_peer_info):
        """Test ProviderRecord initialization with custom timestamp."""
        custom_timestamp = time.time() - 3600  # 1 hour ago
        record = ProviderRecord(sample_peer_info, custom_timestamp)

        assert record.provider_info == sample_peer_info
        assert record.timestamp == custom_timestamp

    def test_provider_record_is_expired(self, sample_peer_info):
        """Test checking if provider record is expired."""
        current_time = time.time()

        # Fresh record
        fresh_record = ProviderRecord(sample_peer_info, current_time)
        assert fresh_record.is_expired() is False

        # Expired record
        expired_timestamp = current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        expired_record = ProviderRecord(sample_peer_info, expired_timestamp)
        assert expired_record.is_expired() is True

    def test_provider_record_should_republish(self, sample_peer_info):
        """Test checking if provider record should be republished."""
        current_time = time.time()

        # Fresh record
        fresh_record = ProviderRecord(sample_peer_info, current_time)
        assert fresh_record.should_republish() is False

        # Record that should be republished
        old_timestamp = current_time - PROVIDER_RECORD_REPUBLISH_INTERVAL - 1
        old_record = ProviderRecord(sample_peer_info, old_timestamp)
        assert old_record.should_republish() is True


class TestProviderStore:
    """Test cases for the ProviderStore class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_id.return_value = ID(b"test_peer_id_12345678901234567890")
        host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        host.get_peerstore.return_value = Mock()
        host.new_stream = AsyncMock()
        return host

    @pytest.fixture
    def mock_peer_routing(self):
        """Create a mock peer routing for testing."""
        peer_routing = Mock()
        peer_routing.find_closest_peers_network = AsyncMock()
        return peer_routing

    @pytest.fixture
    def provider_store(self, mock_host, mock_peer_routing):
        """Create a ProviderStore instance for testing."""
        return ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

    @pytest.fixture
    def provider_store_no_deps(self):
        """Create a ProviderStore instance without dependencies for testing."""
        return ProviderStore()

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = ID(b"provider_peer_id_123456789012345678")
        addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        return PeerInfo(peer_id, addrs)

    def test_provider_store_init_with_deps(self, mock_host, mock_peer_routing):
        """Test ProviderStore initialization with dependencies."""
        ps = ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

        assert ps.host == mock_host
        assert ps.peer_routing == mock_peer_routing
        assert ps.providers == {}

    def test_provider_store_init_without_deps(self):
        """Test ProviderStore initialization without dependencies."""
        ps = ProviderStore()

        assert ps.host is None
        assert ps.peer_routing is None
        assert ps.providers == {}

    def test_add_provider_new_key(self, provider_store, sample_peer_info):
        """Test adding a provider for a new key."""
        key = b"test_key"

        provider_store.add_provider(key, sample_peer_info)

        assert key in provider_store.providers
        peer_id_str = sample_peer_info.peer_id.to_base58()
        assert peer_id_str in provider_store.providers[key]

        record = provider_store.providers[key][peer_id_str]
        assert record.provider_info == sample_peer_info
        assert isinstance(record.timestamp, float)

    def test_add_provider_existing_key(self, provider_store, sample_peer_info):
        """Test adding a provider for an existing key."""
        key = b"test_key"

        # Add first provider
        provider_store.add_provider(key, sample_peer_info)
        initial_timestamp = provider_store.providers[key][
            sample_peer_info.peer_id.to_base58()
        ].timestamp

        # Wait a bit and add same provider again
        time.sleep(0.01)
        provider_store.add_provider(key, sample_peer_info)
        updated_timestamp = provider_store.providers[key][
            sample_peer_info.peer_id.to_base58()
        ].timestamp

        # Should update timestamp
        assert updated_timestamp > initial_timestamp

    def test_add_provider_multiple_providers(self, provider_store):
        """Test adding multiple providers for the same key."""
        key = b"test_key"

        # Create multiple providers
        providers = []
        for i in range(3):
            peer_id = ID(
                f"provider_{i}_id_123456789012345678".encode()[:32].ljust(32, b"\0")
            )
            addrs = [Multiaddr(f"/ip4/127.0.0.{i+1}/tcp/4001")]
            providers.append(PeerInfo(peer_id, addrs))

        # Add all providers
        for provider in providers:
            provider_store.add_provider(key, provider)

        assert key in provider_store.providers
        assert len(provider_store.providers[key]) == 3

        # Verify all providers are stored
        for provider in providers:
            peer_id_str = provider.peer_id.to_base58()
            assert peer_id_str in provider_store.providers[key]

    def test_get_providers_existing_key(self, provider_store):
        """Test getting providers for an existing key."""
        key = b"test_key"

        # Add multiple providers
        providers = []
        for i in range(3):
            peer_id = ID(
                f"provider_{i}_id_123456789012345678".encode()[:32].ljust(32, b"\0")
            )
            addrs = [Multiaddr(f"/ip4/127.0.0.{i+1}/tcp/4001")]
            provider_info = PeerInfo(peer_id, addrs)
            providers.append(provider_info)
            provider_store.add_provider(key, provider_info)

        result = provider_store.get_providers(key)

        assert len(result) == 3
        for provider in providers:
            assert provider in result

    def test_get_providers_non_existing_key(self, provider_store):
        """Test getting providers for a non-existent key."""
        key = b"non_existent_key"

        result = provider_store.get_providers(key)

        assert result == []

    def test_get_providers_with_expired_records(self, provider_store):
        """Test getting providers when some records are expired."""
        key = b"test_key"
        current_time = time.time()

        # Add fresh provider
        fresh_peer_id = ID(b"fresh_provider_id_123456789012345678")
        fresh_provider = PeerInfo(fresh_peer_id, [Multiaddr("/ip4/127.0.0.1/tcp/4001")])
        provider_store.add_provider(key, fresh_provider)

        # Add expired provider manually
        expired_peer_id = ID(b"expired_provider_id_12345678901234567")
        expired_provider = PeerInfo(
            expired_peer_id, [Multiaddr("/ip4/127.0.0.2/tcp/4001")]
        )
        expired_timestamp = current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        expired_record = ProviderRecord(expired_provider, expired_timestamp)

        provider_store.providers[key] = provider_store.providers.get(key, {})
        provider_store.providers[key][expired_peer_id.to_base58()] = expired_record

        result = provider_store.get_providers(key)

        # Should only return fresh provider
        assert len(result) == 1
        assert fresh_provider in result
        assert expired_provider not in result

    def test_cleanup_expired(self, provider_store):
        """Test cleaning up expired provider records."""
        current_time = time.time()

        # Add keys with mixed fresh and expired providers
        key1 = b"key1"
        key2 = b"key2"
        key3 = b"key3"

        # Key1: fresh provider
        fresh_provider = PeerInfo(ID(b"fresh_provider_id_1234567890123456"), [])
        provider_store.add_provider(key1, fresh_provider)

        # Key2: expired provider
        expired_provider = PeerInfo(ID(b"expired_provider_id_123456789012345"), [])
        expired_record = ProviderRecord(
            expired_provider, current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        )
        provider_store.providers[key2] = {
            expired_provider.peer_id.to_base58(): expired_record
        }

        # Key3: mix of fresh and expired
        fresh_provider2 = PeerInfo(ID(b"fresh_provider2_id_123456789012345"), [])
        expired_provider2 = PeerInfo(ID(b"expired_provider2_id_12345678901234"), [])
        provider_store.add_provider(key3, fresh_provider2)
        expired_record2 = ProviderRecord(
            expired_provider2, current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        )
        provider_store.providers[key3][
            expired_provider2.peer_id.to_base58()
        ] = expired_record2

        provider_store.cleanup_expired()

        # Key1 should still exist with fresh provider
        assert key1 in provider_store.providers
        assert len(provider_store.providers[key1]) == 1

        # Key2 should be removed (only had expired provider)
        assert key2 not in provider_store.providers

        # Key3 should exist with only fresh provider
        assert key3 in provider_store.providers
        assert len(provider_store.providers[key3]) == 1
        assert fresh_provider2.peer_id.to_base58() in provider_store.providers[key3]

    def test_get_provided_keys(self, provider_store, sample_peer_info):
        """Test getting keys provided by a specific peer."""
        peer_id = sample_peer_info.peer_id

        # Add provider for multiple keys
        keys = [b"key1", b"key2", b"key3"]
        for key in keys:
            provider_store.add_provider(key, sample_peer_info)

        # Add another provider for one of the keys
        other_peer = PeerInfo(ID(b"other_peer_id_123456789012345678"), [])
        provider_store.add_provider(keys[0], other_peer)

        result = provider_store.get_provided_keys(peer_id)

        assert len(result) == 3
        for key in keys:
            assert key in result

    def test_get_provided_keys_no_keys(self, provider_store):
        """Test getting keys for a peer that provides nothing."""
        peer_id = ID(b"non_provider_peer_id_1234567890123456")

        result = provider_store.get_provided_keys(peer_id)

        assert result == []

    def test_size(self, provider_store):
        """Test getting the total number of provider records."""
        # Empty store
        assert provider_store.size() == 0

        # Add providers
        key1 = b"key1"
        key2 = b"key2"

        provider1 = PeerInfo(ID(b"provider1_id_123456789012345678"), [])
        provider2 = PeerInfo(ID(b"provider2_id_123456789012345678"), [])
        provider3 = PeerInfo(ID(b"provider3_id_123456789012345678"), [])

        provider_store.add_provider(key1, provider1)
        provider_store.add_provider(key1, provider2)
        provider_store.add_provider(key2, provider3)

        assert provider_store.size() == 3

    @pytest.mark.trio
    async def test_provide_success(self, provider_store):
        """Test providing content successfully."""
        key = b"test_key"

        # Mock finding closest peers
        closest_peers = [
            ID(b"peer1_id_123456789012345678901234"),
            ID(b"peer2_id_123456789012345678901234"),
        ]
        provider_store.peer_routing.find_closest_peers_network.return_value = (
            closest_peers
        )

        # Mock successful ADD_PROVIDER sends
        with patch.object(
            provider_store, "_send_add_provider", return_value=True
        ) as mock_send:
            result = await provider_store.provide(key)

            assert result is True
            # Should call _send_add_provider for each closest peer
            assert mock_send.call_count == len(closest_peers)

    @pytest.mark.trio
    async def test_provide_no_peer_routing(self, provider_store_no_deps):
        """Test providing content when peer_routing is not available."""
        key = b"test_key"

        result = await provider_store_no_deps.provide(key)

        assert result is False

    @pytest.mark.trio
    async def test_provide_no_closest_peers(self, provider_store):
        """Test providing content when no closest peers are found."""
        key = b"test_key"

        provider_store.peer_routing.find_closest_peers_network.return_value = []

        result = await provider_store.provide(key)

        assert result is False

    @pytest.mark.trio
    async def test_send_add_provider_success(self, provider_store):
        """Test sending ADD_PROVIDER message successfully."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        # Mock stream operations
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create mock response
        response_msg = Message()
        response_msg.type = Message.MessageType.ADD_PROVIDER
        response_msg.key = key
        response_bytes = response_msg.SerializeToString()

        # Mock stream reading
        mock_stream.read.side_effect = [bytes([len(response_bytes)]), response_bytes]

        provider_store.host.new_stream.return_value = mock_stream

        result = await provider_store._send_add_provider(peer_id, key)

        assert result is True
        mock_stream.write.assert_called()
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_send_add_provider_no_host(self, provider_store_no_deps):
        """Test sending ADD_PROVIDER when no host is available."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        result = await provider_store_no_deps._send_add_provider(peer_id, key)

        assert result is False

    @pytest.mark.trio
    async def test_send_add_provider_connection_error(self, provider_store):
        """Test sending ADD_PROVIDER when connection fails."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        provider_store.host.new_stream.side_effect = Exception("Connection failed")

        result = await provider_store._send_add_provider(peer_id, key)

        assert result is False

    @pytest.mark.trio
    async def test_find_providers_local_only(self, provider_store, sample_peer_info):
        """Test finding providers when we have local providers."""
        key = b"test_key"

        # Add local provider
        provider_store.add_provider(key, sample_peer_info)

        result = await provider_store.find_providers(key, count=10)

        assert len(result) == 1
        assert sample_peer_info in result

    @pytest.mark.trio
    async def test_find_providers_network_search(self, provider_store):
        """Test finding providers through network search."""
        key = b"test_key"

        # Mock network search
        remote_providers = [
            PeerInfo(ID(b"remote_provider1_id_1234567890123456"), []),
            PeerInfo(ID(b"remote_provider2_id_1234567890123456"), []),
        ]

        # Mock finding closest peers
        closest_peers = [ID(b"peer1_id_123456789012345678901234")]
        provider_store.peer_routing.find_closest_peers_network.return_value = (
            closest_peers
        )

        # Mock getting providers from peer
        with patch.object(
            provider_store, "_get_providers_from_peer", return_value=remote_providers
        ) as mock_get:
            result = await provider_store.find_providers(key, count=10)

            assert len(result) >= len(remote_providers)
            for provider in remote_providers:
                assert provider in result
            mock_get.assert_called()

    @pytest.mark.trio
    async def test_find_providers_no_peer_routing(self, provider_store_no_deps):
        """Test finding providers when peer_routing is not available."""
        key = b"test_key"

        result = await provider_store_no_deps.find_providers(key)

        assert result == []

    @pytest.mark.trio
    async def test_get_providers_from_peer_success(self, provider_store):
        """Test getting providers from a remote peer successfully."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        # Mock stream operations
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create mock response with providers
        response_msg = Message()
        response_msg.type = Message.MessageType.GET_PROVIDERS
        response_msg.key = key

        # Add provider to response
        provider_proto = response_msg.providerPeers.add()
        provider_id = ID(b"provider_peer_id_123456789012345678")
        provider_proto.id = provider_id.to_bytes()
        provider_proto.addrs.append(b"/ip4/127.0.0.1/tcp/4001")

        response_bytes = response_msg.SerializeToString()

        # Mock stream reading
        mock_stream.read.side_effect = [bytes([len(response_bytes)]), response_bytes]

        provider_store.host.new_stream.return_value = mock_stream

        result = await provider_store._get_providers_from_peer(peer_id, key)

        assert len(result) == 1
        assert result[0].peer_id == provider_id
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_get_providers_from_peer_connection_error(self, provider_store):
        """Test getting providers when connection fails."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        provider_store.host.new_stream.side_effect = Exception("Connection failed")

        result = await provider_store._get_providers_from_peer(peer_id, key)

        assert result == []

    @pytest.mark.trio
    async def test_republish_provider_records(self, provider_store):
        """Test republishing provider records."""
        current_time = time.time()

        # Add a record that should be republished for our local peer
        key = b"test_key"
        # Use the same peer ID as the local peer ID from mock_host fixture
        local_peer_id = (
            provider_store.local_peer_id
        )  # This should be set from mock_host
        provider_info = PeerInfo(local_peer_id, [])
        old_timestamp = current_time - PROVIDER_RECORD_REPUBLISH_INTERVAL - 1
        old_record = ProviderRecord(provider_info, old_timestamp)
        provider_store.providers[key] = {str(local_peer_id): old_record}

        # Mock providing
        with patch.object(provider_store, "provide", return_value=True) as mock_provide:
            await provider_store._republish_provider_records()

            mock_provide.assert_called_once_with(key)

    def test_constants(self):
        """Test that constants are properly defined."""
        assert PROVIDER_RECORD_REPUBLISH_INTERVAL == 22 * 60 * 60  # 22 hours
        assert PROVIDER_RECORD_EXPIRATION_INTERVAL == 48 * 60 * 60  # 48 hours
        assert PROVIDER_ADDRESS_TTL == 30 * 60  # 30 minutes
        assert PROTOCOL_ID == "/ipfs/kad/1.0.0"

    def test_provider_store_edge_cases(self, provider_store):
        """Test edge cases for provider store operations."""
        # Test with empty key
        empty_key = b""
        provider_info = PeerInfo(ID(b"provider_id_123456789012345678"), [])

        provider_store.add_provider(empty_key, provider_info)
        result = provider_store.get_providers(empty_key)

        assert len(result) == 1
        assert provider_info in result

        # Test with very long key
        long_key = b"a" * 1000
        provider_store.add_provider(long_key, provider_info)
        result = provider_store.get_providers(long_key)

        assert len(result) == 1
        assert provider_info in result

"""
Unit tests for the ProviderStore and ProviderRecord classes in Kademlia DHT.

This module tests the core functionality of provider record management including:
- ProviderRecord creation, expiration, and republish logic
- ProviderStore operations (add, get, cleanup)
- Expiration and TTL handling
- Network operations (mocked)
- Edge cases and error conditions
"""

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

from libp2p.kad_dht.provider_store import (
    PROVIDER_ADDRESS_TTL,
    PROVIDER_RECORD_EXPIRATION_INTERVAL,
    PROVIDER_RECORD_REPUBLISH_INTERVAL,
    ProviderRecord,
    ProviderStore,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

mock_host = Mock()


class TestProviderRecord:
    """Test suite for ProviderRecord class."""

    def test_init_with_default_timestamp(self):
        """Test ProviderRecord initialization with default timestamp."""
        peer_id = ID.from_base58("QmTest123")
        addresses = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
        peer_info = PeerInfo(peer_id, addresses)

        start_time = time.time()
        record = ProviderRecord(peer_info)
        end_time = time.time()

        assert record.provider_info == peer_info
        assert start_time <= record.timestamp <= end_time
        assert record.peer_id == peer_id
        assert record.addresses == addresses

    def test_init_with_custom_timestamp(self):
        """Test ProviderRecord initialization with custom timestamp."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        custom_timestamp = time.time() - 3600  # 1 hour ago

        record = ProviderRecord(peer_info, timestamp=custom_timestamp)

        assert record.timestamp == custom_timestamp

    def test_is_expired_fresh_record(self):
        """Test that fresh records are not expired."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        record = ProviderRecord(peer_info)

        assert not record.is_expired()

    def test_is_expired_old_record(self):
        """Test that old records are expired."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        old_timestamp = time.time() - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        record = ProviderRecord(peer_info, timestamp=old_timestamp)

        assert record.is_expired()

    def test_is_expired_boundary_condition(self):
        """Test expiration at exact boundary."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        boundary_timestamp = time.time() - PROVIDER_RECORD_EXPIRATION_INTERVAL
        record = ProviderRecord(peer_info, timestamp=boundary_timestamp)

        # At the exact boundary, should be expired (implementation uses >)
        assert record.is_expired()

    def test_should_republish_fresh_record(self):
        """Test that fresh records don't need republishing."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        record = ProviderRecord(peer_info)

        assert not record.should_republish()

    def test_should_republish_old_record(self):
        """Test that old records need republishing."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        old_timestamp = time.time() - PROVIDER_RECORD_REPUBLISH_INTERVAL - 1
        record = ProviderRecord(peer_info, timestamp=old_timestamp)

        assert record.should_republish()

    def test_should_republish_boundary_condition(self):
        """Test republish at exact boundary."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        boundary_timestamp = time.time() - PROVIDER_RECORD_REPUBLISH_INTERVAL
        record = ProviderRecord(peer_info, timestamp=boundary_timestamp)

        # At the exact boundary, should need republishing (implementation uses >)
        assert record.should_republish()

    def test_properties(self):
        """Test peer_id and addresses properties."""
        peer_id = ID.from_base58("QmTest123")
        addresses = [
            Multiaddr("/ip4/127.0.0.1/tcp/8000"),
            Multiaddr("/ip6/::1/tcp/8001"),
        ]
        peer_info = PeerInfo(peer_id, addresses)
        record = ProviderRecord(peer_info)

        assert record.peer_id == peer_id
        assert record.addresses == addresses

    def test_empty_addresses(self):
        """Test ProviderRecord with empty address list."""
        peer_id = ID.from_base58("QmTest123")
        peer_info = PeerInfo(peer_id, [])
        record = ProviderRecord(peer_info)

        assert record.addresses == []


class TestProviderStore:
    """Test suite for ProviderStore class."""

    def test_init_empty_store(self):
        """Test that a new ProviderStore is initialized empty."""
        store = ProviderStore(host=mock_host)

        assert len(store.providers) == 0
        assert store.peer_routing is None
        assert len(store.providing_keys) == 0

    def test_init_with_host(self):
        """Test initialization with host."""
        mock_host = Mock()
        mock_peer_id = ID.from_base58("QmTest123")
        mock_host.get_id.return_value = mock_peer_id

        store = ProviderStore(host=mock_host)

        assert store.host == mock_host
        assert store.local_peer_id == mock_peer_id
        assert len(store.providers) == 0

    def test_init_with_host_and_peer_routing(self):
        """Test initialization with both host and peer routing."""
        mock_host = Mock()
        mock_peer_routing = Mock()
        mock_peer_id = ID.from_base58("QmTest123")
        mock_host.get_id.return_value = mock_peer_id

        store = ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

        assert store.host == mock_host
        assert store.peer_routing == mock_peer_routing
        assert store.local_peer_id == mock_peer_id

    def test_add_provider_new_key(self):
        """Test adding a provider for a new key."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"
        peer_id = ID.from_base58("QmTest123")
        addresses = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
        provider = PeerInfo(peer_id, addresses)

        store.add_provider(key, provider)

        assert key in store.providers
        assert str(peer_id) in store.providers[key]

        record = store.providers[key][str(peer_id)]
        assert record.provider_info == provider
        assert isinstance(record.timestamp, float)

    def test_add_provider_existing_key(self):
        """Test adding multiple providers for the same key."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        # Add first provider
        peer_id1 = ID.from_base58("QmTest123")
        provider1 = PeerInfo(peer_id1, [])
        store.add_provider(key, provider1)

        # Add second provider
        peer_id2 = ID.from_base58("QmTest456")
        provider2 = PeerInfo(peer_id2, [])
        store.add_provider(key, provider2)

        assert len(store.providers[key]) == 2
        assert str(peer_id1) in store.providers[key]
        assert str(peer_id2) in store.providers[key]

    def test_add_provider_update_existing(self):
        """Test updating an existing provider."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"
        peer_id = ID.from_base58("QmTest123")

        # Add initial provider
        provider1 = PeerInfo(peer_id, [Multiaddr("/ip4/127.0.0.1/tcp/8000")])
        store.add_provider(key, provider1)
        first_timestamp = store.providers[key][str(peer_id)].timestamp

        # Small delay to ensure timestamp difference
        time.sleep(0.001)

        # Update provider
        provider2 = PeerInfo(peer_id, [Multiaddr("/ip4/127.0.0.1/tcp/8001")])
        store.add_provider(key, provider2)

        # Should have same peer but updated info
        assert len(store.providers[key]) == 1
        assert str(peer_id) in store.providers[key]

        record = store.providers[key][str(peer_id)]
        assert record.provider_info == provider2
        assert record.timestamp > first_timestamp

    def test_get_providers_empty_key(self):
        """Test getting providers for non-existent key."""
        store = ProviderStore(host=mock_host)
        key = b"nonexistent_key"

        providers = store.get_providers(key)

        assert providers == []

    def test_get_providers_valid_records(self):
        """Test getting providers with valid records."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        # Add multiple providers
        peer_id1 = ID.from_base58("QmTest123")
        peer_id2 = ID.from_base58("QmTest456")
        provider1 = PeerInfo(peer_id1, [Multiaddr("/ip4/127.0.0.1/tcp/8000")])
        provider2 = PeerInfo(peer_id2, [Multiaddr("/ip4/127.0.0.1/tcp/8001")])

        store.add_provider(key, provider1)
        store.add_provider(key, provider2)

        providers = store.get_providers(key)

        assert len(providers) == 2
        provider_ids = {p.peer_id for p in providers}
        assert peer_id1 in provider_ids
        assert peer_id2 in provider_ids

    def test_get_providers_expired_records(self):
        """Test that expired records are filtered out and cleaned up."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        # Add valid provider
        peer_id1 = ID.from_base58("QmTest123")
        provider1 = PeerInfo(peer_id1, [])
        store.add_provider(key, provider1)

        # Add expired provider manually
        peer_id2 = ID.from_base58("QmTest456")
        provider2 = PeerInfo(peer_id2, [])
        expired_timestamp = time.time() - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        store.providers[key][str(peer_id2)] = ProviderRecord(
            provider2, expired_timestamp
        )

        providers = store.get_providers(key)

        # Should only return valid provider
        assert len(providers) == 1
        assert providers[0].peer_id == peer_id1

        # Expired provider should be cleaned up
        assert str(peer_id2) not in store.providers[key]

    def test_get_providers_address_ttl(self):
        """Test address TTL handling in get_providers."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"
        peer_id = ID.from_base58("QmTest123")
        addresses = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
        provider = PeerInfo(peer_id, addresses)

        # Add provider with old timestamp (addresses expired but record valid)
        old_timestamp = time.time() - PROVIDER_ADDRESS_TTL - 1
        store.providers[key] = {str(peer_id): ProviderRecord(provider, old_timestamp)}

        providers = store.get_providers(key)

        # Should return provider but with empty addresses
        assert len(providers) == 1
        assert providers[0].peer_id == peer_id
        assert providers[0].addrs == []

    def test_get_providers_cleanup_empty_key(self):
        """Test that keys with no valid providers are removed."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        # Add only expired providers
        peer_id = ID.from_base58("QmTest123")
        provider = PeerInfo(peer_id, [])
        expired_timestamp = time.time() - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        store.providers[key] = {
            str(peer_id): ProviderRecord(provider, expired_timestamp)
        }

        providers = store.get_providers(key)

        assert providers == []
        assert key not in store.providers  # Key should be removed

    def test_cleanup_expired_no_expired_records(self):
        """Test cleanup when there are no expired records."""
        store = ProviderStore(host=mock_host)
        key1 = b"key1"
        key2 = b"key2"

        # Add valid providers
        peer_id1 = ID.from_base58("QmTest123")
        peer_id2 = ID.from_base58("QmTest456")
        provider1 = PeerInfo(peer_id1, [])
        provider2 = PeerInfo(peer_id2, [])

        store.add_provider(key1, provider1)
        store.add_provider(key2, provider2)

        initial_size = store.size()
        store.cleanup_expired()

        assert store.size() == initial_size
        assert key1 in store.providers
        assert key2 in store.providers

    def test_cleanup_expired_with_expired_records(self):
        """Test cleanup removes expired records."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        # Add valid provider
        peer_id1 = ID.from_base58("QmTest123")
        provider1 = PeerInfo(peer_id1, [])
        store.add_provider(key, provider1)

        # Add expired provider
        peer_id2 = ID.from_base58("QmTest456")
        provider2 = PeerInfo(peer_id2, [])
        expired_timestamp = time.time() - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        store.providers[key][str(peer_id2)] = ProviderRecord(
            provider2, expired_timestamp
        )

        assert store.size() == 2
        store.cleanup_expired()

        assert store.size() == 1
        assert str(peer_id1) in store.providers[key]
        assert str(peer_id2) not in store.providers[key]

    def test_cleanup_expired_remove_empty_keys(self):
        """Test that keys with only expired providers are removed."""
        store = ProviderStore(host=mock_host)
        key1 = b"key1"
        key2 = b"key2"

        # Add valid provider to key1
        peer_id1 = ID.from_base58("QmTest123")
        provider1 = PeerInfo(peer_id1, [])
        store.add_provider(key1, provider1)

        # Add only expired provider to key2
        peer_id2 = ID.from_base58("QmTest456")
        provider2 = PeerInfo(peer_id2, [])
        expired_timestamp = time.time() - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
        store.providers[key2] = {
            str(peer_id2): ProviderRecord(provider2, expired_timestamp)
        }

        store.cleanup_expired()

        assert key1 in store.providers
        assert key2 not in store.providers

    def test_get_provided_keys_empty_store(self):
        """Test get_provided_keys with empty store."""
        store = ProviderStore(host=mock_host)
        peer_id = ID.from_base58("QmTest123")

        keys = store.get_provided_keys(peer_id)

        assert keys == []

    def test_get_provided_keys_single_peer(self):
        """Test get_provided_keys for a specific peer."""
        store = ProviderStore(host=mock_host)
        peer_id1 = ID.from_base58("QmTest123")
        peer_id2 = ID.from_base58("QmTest456")

        key1 = b"key1"
        key2 = b"key2"
        key3 = b"key3"

        provider1 = PeerInfo(peer_id1, [])
        provider2 = PeerInfo(peer_id2, [])

        # peer_id1 provides key1 and key2
        store.add_provider(key1, provider1)
        store.add_provider(key2, provider1)

        # peer_id2 provides key2 and key3
        store.add_provider(key2, provider2)
        store.add_provider(key3, provider2)

        keys1 = store.get_provided_keys(peer_id1)
        keys2 = store.get_provided_keys(peer_id2)

        assert len(keys1) == 2
        assert key1 in keys1
        assert key2 in keys1

        assert len(keys2) == 2
        assert key2 in keys2
        assert key3 in keys2

    def test_get_provided_keys_nonexistent_peer(self):
        """Test get_provided_keys for peer that provides nothing."""
        store = ProviderStore(host=mock_host)
        peer_id1 = ID.from_base58("QmTest123")
        peer_id2 = ID.from_base58("QmTest456")

        # Add provider for peer_id1 only
        key = b"key"
        provider = PeerInfo(peer_id1, [])
        store.add_provider(key, provider)

        # Query for peer_id2 (provides nothing)
        keys = store.get_provided_keys(peer_id2)

        assert keys == []

    def test_size_empty_store(self):
        """Test size() with empty store."""
        store = ProviderStore(host=mock_host)

        assert store.size() == 0

    def test_size_with_providers(self):
        """Test size() with multiple providers."""
        store = ProviderStore(host=mock_host)

        # Add providers
        key1 = b"key1"
        key2 = b"key2"
        peer_id1 = ID.from_base58("QmTest123")
        peer_id2 = ID.from_base58("QmTest456")
        peer_id3 = ID.from_base58("QmTest789")

        provider1 = PeerInfo(peer_id1, [])
        provider2 = PeerInfo(peer_id2, [])
        provider3 = PeerInfo(peer_id3, [])

        store.add_provider(key1, provider1)
        store.add_provider(key1, provider2)  # 2 providers for key1
        store.add_provider(key2, provider3)  # 1 provider for key2

        assert store.size() == 3

    @pytest.mark.trio
    async def test_provide_no_host(self):
        """Test provide() returns False when no host is configured."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        result = await store.provide(key)

        assert result is False

    @pytest.mark.trio
    async def test_provide_no_peer_routing(self):
        """Test provide() returns False when no peer routing is configured."""
        mock_host = Mock()
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        result = await store.provide(key)

        assert result is False

    @pytest.mark.trio
    async def test_provide_success(self):
        """Test successful provide operation."""
        # Setup mocks
        mock_host = Mock()
        mock_peer_routing = AsyncMock()
        peer_id = ID.from_base58("QmTest123")

        mock_host.get_id.return_value = peer_id
        mock_host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]

        # Mock finding closest peers
        closest_peers = [ID.from_base58("QmPeer1"), ID.from_base58("QmPeer2")]
        mock_peer_routing.find_closest_peers_network.return_value = closest_peers

        store = ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

        # Mock _send_add_provider to return success
        with patch.object(store, "_send_add_provider", return_value=True) as mock_send:
            key = b"test_key"
            result = await store.provide(key)

            assert result is True
            assert key in store.providing_keys
            assert key in store.providers

            # Should have called _send_add_provider for each peer
            assert mock_send.call_count == len(closest_peers)

    @pytest.mark.trio
    async def test_provide_skip_local_peer(self):
        """Test that provide() skips sending to local peer."""
        # Setup mocks
        mock_host = Mock()
        mock_peer_routing = AsyncMock()
        peer_id = ID.from_base58("QmTest123")

        mock_host.get_id.return_value = peer_id
        mock_host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]

        # Include local peer in closest peers
        closest_peers = [peer_id, ID.from_base58("QmPeer1")]
        mock_peer_routing.find_closest_peers_network.return_value = closest_peers

        store = ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

        with patch.object(store, "_send_add_provider", return_value=True) as mock_send:
            key = b"test_key"
            result = await store.provide(key)

            assert result is True
            # Should only call _send_add_provider once (skip local peer)
            assert mock_send.call_count == 1

    @pytest.mark.trio
    async def test_find_providers_no_host(self):
        """Test find_providers() returns empty list when no host."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"

        result = await store.find_providers(key)

        assert result == []

    @pytest.mark.trio
    async def test_find_providers_local_only(self):
        """Test find_providers() returns local providers."""
        mock_host = Mock()
        mock_peer_routing = Mock()
        store = ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

        # Add local providers
        key = b"test_key"
        peer_id = ID.from_base58("QmTest123")
        provider = PeerInfo(peer_id, [])
        store.add_provider(key, provider)

        result = await store.find_providers(key)

        assert len(result) == 1
        assert result[0].peer_id == peer_id

    @pytest.mark.trio
    async def test_find_providers_network_search(self):
        """Test find_providers() searches network when no local providers."""
        mock_host = Mock()
        mock_peer_routing = AsyncMock()
        store = ProviderStore(host=mock_host, peer_routing=mock_peer_routing)

        # Mock network search
        closest_peers = [ID.from_base58("QmPeer1")]
        mock_peer_routing.find_closest_peers_network.return_value = closest_peers

        # Mock provider response
        remote_peer_id = ID.from_base58("QmRemote123")
        remote_providers = [PeerInfo(remote_peer_id, [])]

        with patch.object(
            store, "_get_providers_from_peer", return_value=remote_providers
        ):
            key = b"test_key"
            result = await store.find_providers(key)

            assert len(result) == 1
            assert result[0].peer_id == remote_peer_id

    @pytest.mark.trio
    async def test_get_providers_from_peer_no_host(self):
        """Test _get_providers_from_peer without host."""
        store = ProviderStore(host=mock_host)
        peer_id = ID.from_base58("QmTest123")
        key = b"test_key"

        # Should handle missing host gracefully
        result = await store._get_providers_from_peer(peer_id, key)
        assert result == []

    def test_edge_case_empty_key(self):
        """Test handling of empty key."""
        store = ProviderStore(host=mock_host)
        key = b""
        peer_id = ID.from_base58("QmTest123")
        provider = PeerInfo(peer_id, [])

        store.add_provider(key, provider)
        providers = store.get_providers(key)

        assert len(providers) == 1
        assert providers[0].peer_id == peer_id

    def test_edge_case_large_key(self):
        """Test handling of large key."""
        store = ProviderStore(host=mock_host)
        key = b"x" * 10000  # 10KB key
        peer_id = ID.from_base58("QmTest123")
        provider = PeerInfo(peer_id, [])

        store.add_provider(key, provider)
        providers = store.get_providers(key)

        assert len(providers) == 1
        assert providers[0].peer_id == peer_id

    def test_concurrent_operations(self):
        """Test multiple concurrent operations."""
        store = ProviderStore(host=mock_host)

        # Add many providers
        num_keys = 100
        num_providers_per_key = 5

        for i in range(num_keys):
            _key = f"key_{i}".encode()
            for j in range(num_providers_per_key):
                # Generate unique valid Base58 peer IDs
                # Use a different approach that ensures uniqueness
                unique_id = i * num_providers_per_key + j + 1  # Ensure > 0
                _peer_id_str = f"QmPeer{unique_id:06d}".replace("0", "A") + "1" * 38
                peer_id = ID.from_base58(_peer_id_str)
                provider = PeerInfo(peer_id, [])
                store.add_provider(_key, provider)

        # Verify total size
        expected_size = num_keys * num_providers_per_key
        assert store.size() == expected_size

        # Verify individual keys
        for i in range(num_keys):
            _key = f"key_{i}".encode()
            providers = store.get_providers(_key)
            assert len(providers) == num_providers_per_key

    def test_memory_efficiency_large_dataset(self):
        """Test memory behavior with large datasets."""
        store = ProviderStore(host=mock_host)

        # Add large number of providers
        num_entries = 1000
        for i in range(num_entries):
            _key = f"key_{i:05d}".encode()
            # Generate valid Base58 peer IDs (replace 0 with valid characters)
            peer_str = f"QmPeer{i:05d}".replace("0", "1") + "1" * 35
            peer_id = ID.from_base58(peer_str)
            provider = PeerInfo(peer_id, [])
            store.add_provider(_key, provider)

        assert store.size() == num_entries

        # Clean up all entries by making them expired
        current_time = time.time()
        for _key, providers in store.providers.items():
            for _peer_id_str, record in providers.items():
                record.timestamp = (
                    current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1
                )

        store.cleanup_expired()
        assert store.size() == 0
        assert len(store.providers) == 0

    def test_unicode_key_handling(self):
        """Test handling of unicode content in keys."""
        store = ProviderStore(host=mock_host)

        # Test various unicode keys
        unicode_keys = [
            b"hello",
            "héllo".encode(),
            "🔑".encode(),
            "ключ".encode(),  # Russian
            "键".encode(),  # Chinese
        ]

        for i, key in enumerate(unicode_keys):
            # Generate valid Base58 peer IDs
            peer_id = ID.from_base58(f"QmPeer{i + 1}" + "1" * 42)  # Valid base58
            provider = PeerInfo(peer_id, [])
            store.add_provider(key, provider)

            providers = store.get_providers(key)
            assert len(providers) == 1
            assert providers[0].peer_id == peer_id

    def test_multiple_addresses_per_provider(self):
        """Test providers with multiple addresses."""
        store = ProviderStore(host=mock_host)
        key = b"test_key"
        peer_id = ID.from_base58("QmTest123")

        addresses = [
            Multiaddr("/ip4/127.0.0.1/tcp/8000"),
            Multiaddr("/ip6/::1/tcp/8001"),
            Multiaddr("/ip4/192.168.1.100/tcp/8002"),
        ]
        provider = PeerInfo(peer_id, addresses)

        store.add_provider(key, provider)
        providers = store.get_providers(key)

        assert len(providers) == 1
        assert providers[0].peer_id == peer_id
        assert len(providers[0].addrs) == len(addresses)
        assert all(addr in providers[0].addrs for addr in addresses)

    @pytest.mark.trio
    async def test_republish_provider_records_no_keys(self):
        """Test _republish_provider_records with no providing keys."""
        store = ProviderStore(host=mock_host)

        # Should complete without error even with no providing keys
        await store._republish_provider_records()

        assert len(store.providing_keys) == 0

    def test_expiration_boundary_conditions(self):
        """Test expiration around boundary conditions."""
        store = ProviderStore(host=mock_host)
        peer_id = ID.from_base58("QmTest123")
        provider = PeerInfo(peer_id, [])

        current_time = time.time()

        # Test records at various timestamps
        timestamps = [
            current_time,  # Fresh
            current_time - PROVIDER_ADDRESS_TTL + 1,  # Addresses valid
            current_time - PROVIDER_ADDRESS_TTL - 1,  # Addresses expired
            current_time
            - PROVIDER_RECORD_REPUBLISH_INTERVAL
            + 1,  # No republish needed
            current_time - PROVIDER_RECORD_REPUBLISH_INTERVAL - 1,  # Republish needed
            current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL + 1,  # Not expired
            current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL - 1,  # Expired
        ]

        for i, timestamp in enumerate(timestamps):
            test_key = f"key_{i}".encode()
            record = ProviderRecord(provider, timestamp)
            store.providers[test_key] = {str(peer_id): record}

        # Test various operations
        for i, timestamp in enumerate(timestamps):
            test_key = f"key_{i}".encode()
            providers = store.get_providers(test_key)

            if timestamp <= current_time - PROVIDER_RECORD_EXPIRATION_INTERVAL:
                # Should be expired and removed
                assert len(providers) == 0
                assert test_key not in store.providers
            else:
                # Should be present
                assert len(providers) == 1
                assert providers[0].peer_id == peer_id

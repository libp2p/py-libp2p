"""
Unit tests for the ValueStore class in Kademlia DHT.

This module tests the core functionality of the ValueStore including:
- Basic storage and retrieval operations
- Expiration and TTL handling
- Edge cases and error conditions
- Store management operations
"""

import time
from unittest.mock import (
    Mock,
)

import pytest

from libp2p.kad_dht.value_store import (
    DEFAULT_TTL,
    ValueStore,
)
from libp2p.peer.id import (
    ID,
)

mock_host = Mock()
peer_id = ID.from_base58("QmTest123")


class TestValueStore:
    """Test suite for ValueStore class."""

    def test_init_empty_store(self):
        """Test that a new ValueStore is initialized empty."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        assert len(store.store) == 0

    def test_init_with_host_and_peer_id(self):
        """Test initialization with host and local peer ID."""
        mock_host = Mock()
        peer_id = ID.from_base58("QmTest123")

        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        assert store.host == mock_host
        assert store.local_peer_id == peer_id
        assert len(store.store) == 0

    def test_put_basic(self):
        """Test basic put operation."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"

        store.put(key, value)

        assert key in store.store
        stored_value, validity = store.store[key]
        assert stored_value == value
        assert validity is not None
        assert validity > time.time()  # Should be in the future

    def test_put_with_custom_validity(self):
        """Test put operation with custom validity time."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"
        custom_validity = time.time() + 3600  # 1 hour from now

        store.put(key, value, validity=custom_validity)

        stored_value, validity = store.store[key]
        assert stored_value == value
        assert validity == custom_validity

    def test_put_overwrite_existing(self):
        """Test that put overwrites existing values."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value1 = b"value1"
        value2 = b"value2"

        store.put(key, value1)
        store.put(key, value2)

        assert len(store.store) == 1
        stored_value, _ = store.store[key]
        assert stored_value == value2

    def test_get_existing_valid_value(self):
        """Test retrieving an existing, non-expired value."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value == value

    def test_get_nonexistent_key(self):
        """Test retrieving a non-existent key returns None."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"nonexistent_key"

        retrieved_value = store.get(key)

        assert retrieved_value is None

    def test_get_expired_value(self):
        """Test that expired values are automatically removed and return None."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"
        expired_validity = time.time() - 1  # 1 second ago

        # Manually insert expired value
        store.store[key] = (value, expired_validity)

        retrieved_value = store.get(key)

        assert retrieved_value is None
        assert key not in store.store  # Should be removed

    def test_remove_existing_key(self):
        """Test removing an existing key."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"

        store.put(key, value)
        result = store.remove(key)

        assert result is True
        assert key not in store.store

    def test_remove_nonexistent_key(self):
        """Test removing a non-existent key returns False."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"nonexistent_key"

        result = store.remove(key)

        assert result is False

    def test_has_existing_valid_key(self):
        """Test has() returns True for existing, valid keys."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"

        store.put(key, value)
        result = store.has(key)

        assert result is True

    def test_has_nonexistent_key(self):
        """Test has() returns False for non-existent keys."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"nonexistent_key"

        result = store.has(key)

        assert result is False

    def test_has_expired_key(self):
        """Test has() returns False for expired keys and removes them."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"
        expired_validity = time.time() - 1

        # Manually insert expired value
        store.store[key] = (value, expired_validity)

        result = store.has(key)

        assert result is False
        assert key not in store.store  # Should be removed

    def test_cleanup_expired_no_expired_values(self):
        """Test cleanup when there are no expired values."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key1 = b"key1"
        key2 = b"key2"
        value = b"value"

        store.put(key1, value)
        store.put(key2, value)

        expired_count = store.cleanup_expired()

        assert expired_count == 0
        assert len(store.store) == 2

    def test_cleanup_expired_with_expired_values(self):
        """Test cleanup removes expired values."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key1 = b"valid_key"
        key2 = b"expired_key1"
        key3 = b"expired_key2"
        value = b"value"
        expired_validity = time.time() - 1

        store.put(key1, value)  # Valid
        store.store[key2] = (value, expired_validity)  # Expired
        store.store[key3] = (value, expired_validity)  # Expired

        expired_count = store.cleanup_expired()

        assert expired_count == 2
        assert len(store.store) == 1
        assert key1 in store.store
        assert key2 not in store.store
        assert key3 not in store.store

    def test_cleanup_expired_mixed_validity_types(self):
        """Test cleanup with mix of values with and without expiration."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key1 = b"no_expiry"
        key2 = b"valid_expiry"
        key3 = b"expired"
        value = b"value"

        # No expiration (None validity)
        store.put(key1, value)
        # Valid expiration
        store.put(key2, value, validity=time.time() + 3600)
        # Expired
        store.store[key3] = (value, time.time() - 1)

        expired_count = store.cleanup_expired()

        assert expired_count == 1
        assert len(store.store) == 2
        assert key1 in store.store
        assert key2 in store.store
        assert key3 not in store.store

    def test_get_keys_empty_store(self):
        """Test get_keys() returns empty list for empty store."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)

        keys = store.get_keys()

        assert keys == []

    def test_get_keys_with_valid_values(self):
        """Test get_keys() returns all non-expired keys."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key1 = b"key1"
        key2 = b"key2"
        key3 = b"expired_key"
        value = b"value"

        store.put(key1, value)
        store.put(key2, value)
        store.store[key3] = (value, time.time() - 1)  # Expired

        keys = store.get_keys()

        assert len(keys) == 2
        assert key1 in keys
        assert key2 in keys
        assert key3 not in keys

    def test_size_empty_store(self):
        """Test size() returns 0 for empty store."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)

        size = store.size()

        assert size == 0

    def test_size_with_valid_values(self):
        """Test size() returns correct count after cleaning expired values."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key1 = b"key1"
        key2 = b"key2"
        key3 = b"expired_key"
        value = b"value"

        store.put(key1, value)
        store.put(key2, value)
        store.store[key3] = (value, time.time() - 1)  # Expired

        size = store.size()

        assert size == 2

    def test_edge_case_empty_key(self):
        """Test handling of empty key."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b""
        value = b"value"

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value == value

    def test_edge_case_empty_value(self):
        """Test handling of empty value."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"
        value = b""

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value == value

    def test_edge_case_large_key_value(self):
        """Test handling of large keys and values."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"x" * 10000  # 10KB key
        value = b"y" * 100000  # 100KB value

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value == value

    def test_edge_case_negative_validity(self):
        """Test handling of negative validity time."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"
        value = b"value"

        store.put(key, value, validity=-1)

        # Should be expired
        retrieved_value = store.get(key)
        assert retrieved_value is None

    def test_default_ttl_calculation(self):
        """Test that default TTL is correctly applied."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"
        value = b"value"
        start_time = time.time()

        store.put(key, value)

        _, validity = store.store[key]
        expected_validity = start_time + DEFAULT_TTL

        # Allow small time difference for execution
        assert abs(validity - expected_validity) < 1

    def test_concurrent_operations(self):
        """Test that multiple operations don't interfere with each other."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)

        # Add multiple key-value pairs
        for i in range(100):
            key = f"key_{i}".encode()
            value = f"value_{i}".encode()
            store.put(key, value)

        # Verify all are stored
        assert store.size() == 100

        # Remove every other key
        for i in range(0, 100, 2):
            key = f"key_{i}".encode()
            store.remove(key)

        # Verify correct count
        assert store.size() == 50

        # Verify remaining keys are correct
        for i in range(1, 100, 2):
            key = f"key_{i}".encode()
            assert store.has(key)

    def test_expiration_boundary_conditions(self):
        """Test expiration around current time boundary."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key1 = b"key1"
        key2 = b"key2"
        key3 = b"key3"
        value = b"value"
        current_time = time.time()

        # Just expired
        store.store[key1] = (value, current_time - 0.001)
        # Valid for a longer time to account for test execution time
        store.store[key2] = (value, current_time + 1.0)
        # Exactly current time (should be expired)
        store.store[key3] = (value, current_time)

        # Small delay to ensure time has passed
        time.sleep(0.002)

        assert not store.has(key1)  # Should be expired
        assert store.has(key2)  # Should be valid
        assert not store.has(key3)  # Should be expired (exactly at current time)

    def test_store_internal_structure(self):
        """Test that internal store structure is maintained correctly."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"
        value = b"value"
        validity = time.time() + 3600

        store.put(key, value, validity=validity)

        # Verify internal structure
        assert isinstance(store.store, dict)
        assert key in store.store
        stored_tuple = store.store[key]
        assert isinstance(stored_tuple, tuple)
        assert len(stored_tuple) == 2
        assert stored_tuple[0] == value
        assert stored_tuple[1] == validity

    @pytest.mark.trio
    async def test_store_at_peer_local_peer(self):
        """Test _store_at_peer returns True when storing at local peer."""
        mock_host = Mock()
        peer_id = ID.from_base58("QmTest123")
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"
        value = b"value"

        result = await store._store_at_peer(peer_id, key, value)

        assert result is True

    @pytest.mark.trio
    async def test_get_from_peer_local_peer(self):
        """Test _get_from_peer returns None when querying local peer."""
        mock_host = Mock()
        peer_id = ID.from_base58("QmTest123")
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"

        result = await store._get_from_peer(peer_id, key)

        assert result is None

    def test_memory_efficiency_large_dataset(self):
        """Test memory behavior with large datasets."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)

        # Add a large number of entries
        num_entries = 10000
        for i in range(num_entries):
            key = f"key_{i:05d}".encode()
            value = f"value_{i:05d}".encode()
            store.put(key, value)

        assert store.size() == num_entries

        # Clean up all entries
        for i in range(num_entries):
            key = f"key_{i:05d}".encode()
            store.remove(key)

        assert store.size() == 0
        assert len(store.store) == 0

    def test_key_collision_resistance(self):
        """Test that similar keys don't collide."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)

        # Test keys that might cause collisions
        keys = [
            b"key",
            b"key\x00",
            b"key1",
            b"Key",  # Different case
            b"key ",  # With space
            b" key",  # Leading space
        ]

        for i, key in enumerate(keys):
            value = f"value_{i}".encode()
            store.put(key, value)

        # Verify all keys are stored separately
        assert store.size() == len(keys)

        for i, key in enumerate(keys):
            expected_value = f"value_{i}".encode()
            assert store.get(key) == expected_value

    def test_unicode_key_handling(self):
        """Test handling of unicode content in keys."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)

        # Test various unicode keys
        unicode_keys = [
            b"hello",
            "héllo".encode(),
            "🔑".encode(),
            "ключ".encode(),  # Russian
            "键".encode(),  # Chinese
        ]

        for i, key in enumerate(unicode_keys):
            value = f"value_{i}".encode()
            store.put(key, value)
            assert store.get(key) == value

"""
Unit tests for the Kademlia DHT value store implementation.

This module contains unit tests for the ValueStore class.
"""

import logging
import time
from unittest.mock import (
    AsyncMock,
    Mock,
)

import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.kad_dht.pb.kademlia_pb2 import (
    Message,
)
from libp2p.kad_dht.value_store import (
    DEFAULT_TTL,
    PROTOCOL_ID,
    ValueStore,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)

logger = logging.getLogger("test.value_store")


class TestValueStore:
    """Test cases for the ValueStore class."""

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
    def local_peer_id(self):
        """Create a local peer ID for testing."""
        return ID(b"local_peer_id_123456789012345678")

    @pytest.fixture
    def value_store(self, mock_host, local_peer_id):
        """Create a ValueStore instance for testing."""
        return ValueStore(host=mock_host, local_peer_id=local_peer_id)

    @pytest.fixture
    def value_store_no_host(self, local_peer_id):
        """Create a ValueStore instance without host for testing."""
        return ValueStore(local_peer_id=local_peer_id)

    def test_value_store_init_with_host(self, mock_host, local_peer_id):
        """Test ValueStore initialization with host."""
        vs = ValueStore(host=mock_host, local_peer_id=local_peer_id)

        assert vs.host == mock_host
        assert vs.local_peer_id == local_peer_id
        assert vs.store == {}

    def test_value_store_init_without_host(self, local_peer_id):
        """Test ValueStore initialization without host."""
        vs = ValueStore(local_peer_id=local_peer_id)

        assert vs.host is None
        assert vs.local_peer_id == local_peer_id
        assert vs.store == {}

    def test_put_value_with_validity(self, value_store):
        """Test storing a value with custom validity."""
        key = b"test_key"
        value = b"test_value"
        validity = time.time() + 3600  # 1 hour from now

        value_store.put(key, value, validity)

        assert key in value_store.store
        stored_value, stored_validity = value_store.store[key]
        assert stored_value == value
        assert stored_validity == validity

    def test_put_value_default_validity(self, value_store):
        """Test storing a value with default validity."""
        key = b"test_key"
        value = b"test_value"

        before_time = time.time()
        value_store.put(key, value)
        after_time = time.time()

        assert key in value_store.store
        stored_value, stored_validity = value_store.store[key]
        assert stored_value == value
        # Should be approximately DEFAULT_TTL seconds from now
        assert before_time + DEFAULT_TTL <= stored_validity <= after_time + DEFAULT_TTL

    def test_get_value_exists(self, value_store):
        """Test retrieving an existing value."""
        key = b"test_key"
        value = b"test_value"
        validity = time.time() + 3600  # Valid for 1 hour

        value_store.store[key] = (value, validity)

        result = value_store.get(key)
        assert result == value

    def test_get_value_not_exists(self, value_store):
        """Test retrieving a non-existent value."""
        key = b"non_existent_key"

        result = value_store.get(key)
        assert result is None

    def test_get_value_expired(self, value_store):
        """Test retrieving an expired value."""
        key = b"test_key"
        value = b"test_value"
        validity = time.time() - 3600  # Expired 1 hour ago

        value_store.store[key] = (value, validity)

        result = value_store.get(key)
        assert result is None
        # Should be removed from store
        assert key not in value_store.store

    def test_remove_existing_value(self, value_store):
        """Test removing an existing value."""
        key = b"test_key"
        value = b"test_value"

        value_store.store[key] = (value, time.time() + 3600)

        result = value_store.remove(key)
        assert result is True
        assert key not in value_store.store

    def test_remove_non_existing_value(self, value_store):
        """Test removing a non-existent value."""
        key = b"non_existent_key"

        result = value_store.remove(key)
        assert result is False

    def test_has_existing_value(self, value_store):
        """Test checking if a value exists."""
        key = b"test_key"
        value = b"test_value"
        validity = time.time() + 3600  # Valid for 1 hour

        value_store.store[key] = (value, validity)

        result = value_store.has(key)
        assert result is True

    def test_has_non_existing_value(self, value_store):
        """Test checking if a non-existent value exists."""
        key = b"non_existent_key"

        result = value_store.has(key)
        assert result is False

    def test_has_expired_value(self, value_store):
        """Test checking if an expired value exists."""
        key = b"test_key"
        value = b"test_value"
        validity = time.time() - 3600  # Expired 1 hour ago

        value_store.store[key] = (value, validity)

        result = value_store.has(key)
        assert result is False
        # Should be removed from store
        assert key not in value_store.store

    def test_cleanup_expired(self, value_store):
        """Test cleaning up expired values."""
        current_time = time.time()

        # Add valid value
        valid_key = b"valid_key"
        value_store.store[valid_key] = (b"valid_value", current_time + 3600)

        # Add expired value
        expired_key = b"expired_key"
        value_store.store[expired_key] = (b"expired_value", current_time - 3600)

        # Add value with no expiration (None validity)
        permanent_key = b"permanent_key"
        value_store.store[permanent_key] = (b"permanent_value", None)

        count = value_store.cleanup_expired()

        assert count == 1  # Only one expired value
        assert valid_key in value_store.store
        assert expired_key not in value_store.store
        assert permanent_key in value_store.store

    def test_get_keys(self, value_store):
        """Test getting all keys."""
        current_time = time.time()

        # Add valid values
        key1 = b"key1"
        key2 = b"key2"
        value_store.store[key1] = (b"value1", current_time + 3600)
        value_store.store[key2] = (b"value2", current_time + 3600)

        # Add expired value
        expired_key = b"expired_key"
        value_store.store[expired_key] = (b"expired_value", current_time - 3600)

        keys = value_store.get_keys()

        assert len(keys) == 2
        assert key1 in keys
        assert key2 in keys
        assert expired_key not in keys

    def test_size(self, value_store):
        """Test getting store size."""
        current_time = time.time()

        # Empty store
        assert value_store.size() == 0

        # Add valid values
        value_store.store[b"key1"] = (b"value1", current_time + 3600)
        value_store.store[b"key2"] = (b"value2", current_time + 3600)

        # Add expired value
        value_store.store[b"expired_key"] = (b"expired_value", current_time - 3600)

        size = value_store.size()

        assert size == 2  # Expired value should be cleaned up

    @pytest.mark.trio
    async def test_store_at_peer_success(self, value_store):
        """Test storing a value at a remote peer successfully."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"
        value = b"test_value"

        # Mock stream operations
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create mock response
        response_msg = Message()
        response_msg.type = Message.MessageType.PUT_VALUE
        response_msg.key = key
        response_bytes = response_msg.SerializeToString()

        # Mock stream reading (varint + message)
        mock_stream.read.side_effect = [b"\x01", response_bytes]  # varint length prefix

        value_store.host.new_stream.return_value = mock_stream

        result = await value_store._store_at_peer(peer_id, key, value)

        assert result is True
        mock_stream.write.assert_called()
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_store_at_peer_self(self, value_store):
        """Test storing a value at self should return True."""
        key = b"test_key"
        value = b"test_value"

        result = await value_store._store_at_peer(value_store.local_peer_id, key, value)

        assert result is True

    @pytest.mark.trio
    async def test_store_at_peer_no_host(self, value_store_no_host):
        """Test storing a value when no host is available."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"
        value = b"test_value"

        result = await value_store_no_host._store_at_peer(peer_id, key, value)

        assert result is False

    @pytest.mark.trio
    async def test_store_at_peer_connection_error(self, value_store):
        """Test storing a value when connection fails."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"
        value = b"test_value"

        value_store.host.new_stream.side_effect = Exception("Connection failed")

        result = await value_store._store_at_peer(peer_id, key, value)

        assert result is False

    @pytest.mark.trio
    async def test_get_from_peer_success(self, value_store):
        """Test getting a value from a remote peer successfully."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"
        value = b"test_value"

        # Mock stream operations
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create mock response
        response_msg = Message()
        response_msg.type = Message.MessageType.GET_VALUE
        response_msg.key = key
        response_msg.record.key = key
        response_msg.record.value = value
        response_bytes = response_msg.SerializeToString()

        # Mock stream reading (varint + message)
        mock_stream.read.side_effect = [
            bytes([len(response_bytes)]),  # varint length prefix
            response_bytes,
        ]

        value_store.host.new_stream.return_value = mock_stream

        result = await value_store._get_from_peer(peer_id, key)

        assert result == value
        mock_stream.write.assert_called()
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_get_from_peer_self(self, value_store):
        """Test getting a value from self should return None."""
        key = b"test_key"

        result = await value_store._get_from_peer(value_store.local_peer_id, key)

        assert result is None

    @pytest.mark.trio
    async def test_get_from_peer_not_found(self, value_store):
        """Test getting a value when peer doesn't have it."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        # Mock stream operations
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create mock response without value
        response_msg = Message()
        response_msg.type = Message.MessageType.GET_VALUE
        response_msg.key = key
        # No record field set
        response_bytes = response_msg.SerializeToString()

        # Mock stream reading
        mock_stream.read.side_effect = [bytes([len(response_bytes)]), response_bytes]

        value_store.host.new_stream.return_value = mock_stream

        result = await value_store._get_from_peer(peer_id, key)

        assert result is None
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_get_from_peer_connection_error(self, value_store):
        """Test getting a value when connection fails."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        value_store.host.new_stream.side_effect = Exception("Connection failed")

        result = await value_store._get_from_peer(peer_id, key)

        assert result is None

    @pytest.mark.trio
    async def test_get_from_peer_stream_error(self, value_store):
        """Test getting a value when stream operations fail."""
        peer_id = ID(b"remote_peer_id_123456789012345678")
        key = b"test_key"

        # Mock stream that fails during read
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read.side_effect = Exception("Stream read failed")
        mock_stream.close = AsyncMock()

        value_store.host.new_stream.return_value = mock_stream

        result = await value_store._get_from_peer(peer_id, key)

        assert result is None
        mock_stream.close.assert_called_once()

    def test_constants(self):
        """Test that constants are properly defined."""
        assert DEFAULT_TTL == 24 * 60 * 60  # 24 hours
        assert PROTOCOL_ID == "/ipfs/kad/1.0.0"

    def test_value_store_with_none_validity(self, value_store):
        """Test storing and retrieving value with None validity (no expiration)."""
        key = b"permanent_key"
        value = b"permanent_value"

        value_store.store[key] = (value, None)

        # Should be retrievable
        result = value_store.get(key)
        assert result == value

        # Should exist
        assert value_store.has(key) is True

        # Should not be cleaned up
        count = value_store.cleanup_expired()
        assert count == 0
        assert key in value_store.store

    def test_store_operations_with_bytes_keys(self, value_store):
        """Test various operations with bytes keys of different lengths."""
        # Test with various key lengths
        keys_values = [
            (b"short", b"value1"),
            (b"a_much_longer_key_that_spans_multiple_bytes", b"value2"),
            (b"\x00\x01\x02\x03\x04\x05", b"binary_value"),
            (b"", b"empty_key_value"),  # Edge case: empty key
        ]

        for key, value in keys_values:
            value_store.put(key, value)
            assert value_store.get(key) == value
            assert value_store.has(key) is True

        # Verify all keys are present
        all_keys = value_store.get_keys()
        for key, _ in keys_values:
            assert key in all_keys

        assert value_store.size() == len(keys_values)

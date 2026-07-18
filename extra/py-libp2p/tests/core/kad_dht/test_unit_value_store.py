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

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.value_store import (
    DEFAULT_TTL,
    ValueStore,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.records.record import make_put_record

# Create a real key pair for signing
key_pair = create_new_key_pair()
mock_host = Mock()
mock_host.get_private_key.return_value = key_pair.private_key
peer_id = ID.from_pubkey(key_pair.public_key)


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
        stored_value_record, validity = store.store[key]
        assert stored_value_record.value == value
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
        assert stored_value.value == value
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
        assert stored_value.value == value2

    def test_get_existing_valid_value(self):
        """Test retrieving an existing, non-expired value."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"test_key"
        value = b"test_value"

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value is not None
        assert retrieved_value.value == value

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
        record = make_put_record(key, value)
        store.store[key] = (record, expired_validity)

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

        record = make_put_record(key, value)
        # Manually insert expired value
        store.store[key] = (record, expired_validity)

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

        record2 = make_put_record(key2, value)
        record3 = make_put_record(key3, value)

        store.put(key1, value)  # Valid
        store.store[key2] = (record2, expired_validity)  # Expired
        store.store[key3] = (record3, expired_validity)  # Expired

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
        record3 = make_put_record(key3, value)
        store.store[key3] = (record3, time.time() - 1)

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

        record3 = make_put_record(key3, value)
        store.store[key3] = (record3, time.time() - 1)  # Expired

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

        record3 = make_put_record(key3, value)
        store.store[key3] = (record3, time.time() - 1)  # Expired

        size = store.size()

        assert size == 2

    def test_edge_case_empty_key(self):
        """Test handling of empty key."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b""
        value = b"value"

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value is not None
        assert retrieved_value.value == value

    def test_edge_case_empty_value(self):
        """Test handling of empty value."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"key"
        value = b""

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value is not None
        assert retrieved_value.value == value

    def test_edge_case_large_key_value(self):
        """Test handling of large keys and values."""
        store = ValueStore(host=mock_host, local_peer_id=peer_id)
        key = b"x" * 10000  # 10KB key
        value = b"y" * 100000  # 100KB value

        store.put(key, value)
        retrieved_value = store.get(key)

        assert retrieved_value is not None
        assert retrieved_value.value == value

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

        record1 = make_put_record(key1, value)
        record2 = make_put_record(key2, value)
        record3 = make_put_record(key3, value)
        # Just expired
        store.store[key1] = (record1, current_time - 0.001)
        # Valid for a longer time to account for test execution time
        store.store[key2] = (record2, current_time + 1.0)
        # Exactly current time (should be expired)
        store.store[key3] = (record3, current_time)

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
        assert stored_tuple[0].value == value
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
    async def test_store_at_peer_propagates_signature_and_author(self):
        """
        _store_at_peer must include signature and author from the locally-stored
        signed record in the outbound PUT_VALUE message.

        This ensures signed-record authenticity is preserved when replicating
        values to remote peers, matching go-libp2p interoperability requirements.
        """
        import varint

        from libp2p.kad_dht.pb.kademlia_pb2 import Message

        # Build a host with a real key pair so put() creates a genuine signed record
        kp = create_new_key_pair()
        remote_peer_id = ID.from_base58("QmRemote123456789")
        local_peer_id = ID.from_pubkey(kp.public_key)

        # Capture the bytes written to the mock stream
        written: list[bytes] = []

        mock_stream = Mock()

        async def _write(data: bytes) -> None:
            written.append(data)

        async def _read(n: int) -> bytes:
            # Simulate a minimal valid PUT_VALUE acknowledgement
            resp = Message()
            resp.type = Message.MessageType.PUT_VALUE
            resp.key = b"test_key"
            raw = resp.SerializeToString()
            length = varint.encode(len(raw))
            # Return one byte at a time for the varint reader, then the body
            full = length + raw
            if not hasattr(_read, "_buf"):
                _read._buf = iter(full)  # type: ignore[attr-defined]
            byte_val = next(_read._buf, b"")  # type: ignore[attr-defined]
            return bytes([byte_val]) if isinstance(byte_val, int) else byte_val

        mock_stream.write = Mock(side_effect=_write)
        mock_stream.read = Mock(side_effect=_read)
        mock_stream.close = Mock(return_value=None)

        # Patch close to be awaitable
        async def _close() -> None:
            pass

        mock_stream.close = _close

        h = Mock()
        h.get_private_key.return_value = kp.private_key
        h.get_peerstore.return_value = Mock()

        # env_to_send_in_RPC is called; return empty bytes to keep test simple
        from libp2p.peer.peerstore import env_to_send_in_RPC

        original_env = env_to_send_in_RPC

        import libp2p.kad_dht.value_store as vs_module

        vs_module.env_to_send_in_RPC = Mock(return_value=(b"", None))  # type: ignore[attr-defined]

        async def _new_stream(*_args: object, **_kwargs: object) -> object:
            return mock_stream

        h.new_stream = _new_stream

        try:
            store = ValueStore(host=h, local_peer_id=local_peer_id)
            key = b"test_key"
            value = b"test_value"

            # Store locally first (creates signed record)
            store.put(key, value)

            # Confirm the local record has signature and author set
            local_record, _ = store.store[key]
            assert local_record.signature, "put() must produce a non-empty signature"
            assert local_record.author, "put() must populate the author field"

            # Now replicate to a remote peer
            await store._store_at_peer(remote_peer_id, key, value)

            # Reconstruct the serialized message from what was written
            # written[0] is the varint length prefix, written[1] is the proto body
            assert len(written) >= 2, "Expected varint + proto body to be written"
            sent_msg = Message()
            sent_msg.ParseFromString(written[1])

            assert sent_msg.HasField("record"), "Outbound message must contain a record"
            assert (
                sent_msg.record.signature == local_record.signature
            ), "Outbound record must carry the signature from the signed record"
            assert (
                sent_msg.record.author == local_record.author
            ), "Outbound record must carry the author from the signed record"
        finally:
            vs_module.env_to_send_in_RPC = original_env  # type: ignore[attr-defined]

    @pytest.mark.trio
    async def test_store_at_peer_signs_record_without_prior_put(self):
        """
        When _store_at_peer is called without a prior put() (e.g. the get_value
        propagation path), it must still produce a signed outbound record —
        never a bare unsigned one.
        """
        import varint

        from libp2p.kad_dht.pb.kademlia_pb2 import Message

        kp = create_new_key_pair()
        remote_peer_id = ID.from_base58("QmRemote999")
        local_peer_id = ID.from_pubkey(kp.public_key)

        written: list[bytes] = []

        async def _write(data: bytes) -> None:
            written.append(data)

        mock_stream = Mock()
        resp = Message()
        resp.type = Message.MessageType.PUT_VALUE
        resp.key = b"bare_key"
        raw = resp.SerializeToString()
        resp_bytes = varint.encode(len(raw)) + raw
        resp_iter = iter(resp_bytes)

        async def _read(n: int) -> bytes:
            byte_val = next(resp_iter, b"")
            return bytes([byte_val]) if isinstance(byte_val, int) else byte_val

        mock_stream.write = Mock(side_effect=_write)
        mock_stream.read = Mock(side_effect=_read)

        async def _close() -> None:
            pass

        mock_stream.close = _close

        h = Mock()
        h.get_private_key.return_value = kp.private_key

        import libp2p.kad_dht.value_store as vs_module

        original_env = vs_module.env_to_send_in_RPC
        vs_module.env_to_send_in_RPC = Mock(return_value=(b"", None))  # type: ignore[attr-defined]

        async def _new_stream(*_args: object, **_kwargs: object) -> object:
            return mock_stream

        h.new_stream = _new_stream

        try:
            store = ValueStore(host=h, local_peer_id=local_peer_id)
            key = b"bare_key"
            value = b"bare_value"

            # Do NOT call store.put() — _store_at_peer must sign the record itself
            await store._store_at_peer(remote_peer_id, key, value)

            assert len(written) >= 2
            sent_msg = Message()
            sent_msg.ParseFromString(written[1])
            assert sent_msg.record.key == key
            assert sent_msg.record.value == value
            # The record must be signed even without a prior put()
            assert sent_msg.record.signature, "record must be signed inline"
            assert sent_msg.record.author, "record must carry author field"
        finally:
            vs_module.env_to_send_in_RPC = original_env  # type: ignore[attr-defined]

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

            retrieved_value = store.get(key)

            assert retrieved_value is not None
            assert retrieved_value.value == expected_value

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

            retrieved_value = store.get(key)

            assert retrieved_value is not None
            assert retrieved_value.value == value

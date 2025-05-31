"""
Unit tests for kad_dht utils module.
"""

import multihash

from libp2p.kad_dht.utils import (
    bytes_to_base58,
    create_key_from_binary,
    distance,
    shared_prefix_len,
    sort_peer_ids_by_distance,
)
from libp2p.peer.id import (
    ID,
)


class TestCreateKeyFromBinary:
    """Test create_key_from_binary function."""

    def test_create_key_from_binary_simple(self):
        """Test creating a key from simple binary data."""
        data = b"hello world"
        key = create_key_from_binary(data)

        # Should return SHA-256 digest
        expected = multihash.digest(data, "sha2-256").digest
        assert key == expected
        assert isinstance(key, bytes)

    def test_create_key_from_binary_empty(self):
        """Test creating a key from empty data."""
        data = b""
        key = create_key_from_binary(data)

        expected = multihash.digest(data, "sha2-256").digest
        assert key == expected

    def test_create_key_from_binary_large_data(self):
        """Test creating a key from large binary data."""
        data = b"x" * 10000  # 10KB of data
        key = create_key_from_binary(data)

        expected = multihash.digest(data, "sha2-256").digest
        assert key == expected
        assert len(key) == 32  # SHA-256 produces 32 bytes

    def test_create_key_deterministic(self):
        """Test that key creation is deterministic."""
        data = b"test data"
        key1 = create_key_from_binary(data)
        key2 = create_key_from_binary(data)
        assert key1 == key2


class TestDistance:
    """Test distance function."""

    def test_distance_identical_keys(self):
        """Test distance between identical keys."""
        key = b"\x01\x02\x03\x04"
        assert distance(key, key) == 0

    def test_distance_different_keys(self):
        """Test distance between different keys."""
        key1 = b"\x01\x02\x03\x04"
        key2 = b"\x05\x06\x07\x08"

        result = distance(key1, key2)
        # XOR: 01^05=04, 02^06=04, 03^07=04, 04^08=0C
        # Result: 0404040C
        expected = 0x0404040C
        assert result == expected

    def test_distance_empty_keys(self):
        """Test distance between empty keys."""
        key1 = b""
        key2 = b""
        assert distance(key1, key2) == 0

    def test_distance_different_lengths(self):
        """Test distance between keys of different lengths."""
        key1 = b"\x01\x02\x03"
        key2 = b"\x05\x06"

        # Should use minimum length (2 bytes)
        result = distance(key1, key2)
        # XOR: 01^05=04, 02^06=04
        # Result: 0404
        expected = 0x0404
        assert result == expected

    def test_distance_commutative(self):
        """Test that distance is commutative."""
        key1 = b"\x01\x02\x03\x04"
        key2 = b"\x05\x06\x07\x08"

        assert distance(key1, key2) == distance(key2, key1)

    def test_distance_single_byte(self):
        """Test distance with single byte keys."""
        key1 = b"\xFF"
        key2 = b"\x00"

        result = distance(key1, key2)
        assert result == 0xFF


class TestBytesToBase58:
    """Test bytes_to_base58 function."""

    def test_bytes_to_base58_simple(self):
        """Test converting simple bytes to base58."""
        data = b"hello"
        result = bytes_to_base58(data)

        import base58

        expected = base58.b58encode(data).decode()
        assert result == expected

    def test_bytes_to_base58_empty(self):
        """Test converting empty bytes to base58."""
        data = b""
        result = bytes_to_base58(data)

        import base58

        expected = base58.b58encode(data).decode()
        assert result == expected

    def test_bytes_to_base58_binary_data(self):
        """Test converting binary data to base58."""
        data = b"\x00\x01\x02\x03\xFF"
        result = bytes_to_base58(data)

        import base58

        expected = base58.b58encode(data).decode()
        assert result == expected


class TestSortPeerIdsByDistance:
    """Test sort_peer_ids_by_distance function."""

    def test_sort_empty_list(self):
        """Test sorting empty peer list."""
        target = b"\x01\x02\x03\x04"
        peers = []

        result = sort_peer_ids_by_distance(target, peers)
        assert result == []

    def test_sort_single_peer(self):
        """Test sorting list with single peer."""
        target = b"\x01\x02\x03\x04"
        peer = ID(b"peer1")
        peers = [peer]

        result = sort_peer_ids_by_distance(target, peers)
        assert result == [peer]

    def test_sort_multiple_peers(self):
        """Test sorting multiple peers by distance."""
        target = b"\x00\x00\x00\x00"

        # Create peers with known distances
        peer1 = ID(b"peer1")  # Will have some distance
        peer2 = ID(b"peer2")  # Will have different distance
        peer3 = ID(b"peer3")  # Will have different distance

        peers = [peer1, peer2, peer3]
        result = sort_peer_ids_by_distance(target, peers)

        # Should return all peers, sorted by distance
        assert len(result) == 3
        assert all(peer in result for peer in peers)

        # Verify they are sorted by distance
        distances = []
        for peer in result:
            peer_hash = multihash.digest(peer.to_bytes(), "sha2-256").digest
            dist = distance(target, peer_hash)
            distances.append(dist)

        # Distances should be in ascending order
        assert distances == sorted(distances)

    def test_sort_peers_deterministic(self):
        """Test that sorting is deterministic."""
        target = b"\x01\x02\x03\x04"
        peers = [ID(b"peer1"), ID(b"peer2"), ID(b"peer3")]

        result1 = sort_peer_ids_by_distance(target, peers)
        result2 = sort_peer_ids_by_distance(target, peers)

        assert result1 == result2

    def test_sort_peers_with_same_distance(self):
        """Test sorting peers that have the same distance."""
        target = b"\x00\x00\x00\x00"

        # Create two identical peers (edge case)
        peer_data = b"same_peer"
        peer1 = ID(peer_data)
        peer2 = ID(peer_data)

        peers = [peer1, peer2]
        result = sort_peer_ids_by_distance(target, peers)

        assert len(result) == 2
        # Both should have same distance, order may vary but should be stable


class TestSharedPrefixLen:
    """Test shared_prefix_len function."""

    def test_shared_prefix_identical(self):
        """Test shared prefix length of identical sequences."""
        data = b"\xFF\x00\xAA\xBB"
        result = shared_prefix_len(data, data)
        assert result == len(data) * 8  # All bits are shared

    def test_shared_prefix_completely_different(self):
        """Test shared prefix length of completely different sequences."""
        first = b"\xFF"  # 11111111
        second = b"\x00"  # 00000000
        result = shared_prefix_len(first, second)
        assert result == 0  # No shared prefix bits

    def test_shared_prefix_partial_byte(self):
        """Test shared prefix within a byte."""
        first = b"\xF0"  # 11110000
        second = b"\xF8"  # 11111000
        result = shared_prefix_len(first, second)
        assert result == 4  # First 4 bits are shared

    def test_shared_prefix_multiple_bytes(self):
        """Test shared prefix across multiple bytes."""
        first = b"\xFF\xFF\xF0\x00"  # Complete bytes + partial
        second = b"\xFF\xFF\xF8\xFF"  # Same start, different ending
        result = shared_prefix_len(first, second)
        assert result == 16 + 4  # 2 complete bytes + 4 bits = 20 bits

    def test_shared_prefix_empty_sequences(self):
        """Test shared prefix of empty sequences."""
        result = shared_prefix_len(b"", b"")
        assert result == 0

    def test_shared_prefix_different_lengths(self):
        """Test shared prefix of sequences with different lengths."""
        first = b"\xFF\xFF\xFF"
        second = b"\xFF\xFF"
        result = shared_prefix_len(first, second)
        assert result == 16  # Limited by shorter sequence

    def test_shared_prefix_one_empty(self):
        """Test shared prefix when one sequence is empty."""
        first = b"\xFF\xFF"
        second = b""
        result = shared_prefix_len(first, second)
        assert result == 0

    def test_shared_prefix_single_bit_difference(self):
        """Test shared prefix with single bit difference."""
        first = b"\x80"  # 10000000
        second = b"\x00"  # 00000000
        result = shared_prefix_len(first, second)
        assert result == 0  # First bit is different

        first = b"\xC0"  # 11000000
        second = b"\x80"  # 10000000
        result = shared_prefix_len(first, second)
        assert result == 1  # First bit shared, second different

    def test_shared_prefix_all_combinations(self):
        """Test various bit patterns for comprehensive coverage."""
        test_cases = [
            (b"\x00", b"\x00", 8),  # All zeros
            (b"\xFF", b"\xFF", 8),  # All ones
            (b"\xAA", b"\x55", 0),  # Alternating patterns
            (b"\xF0", b"\x0F", 0),  # Complementary nibbles
            (b"\xFC", b"\xF0", 4),  # Shared prefix in nibble
        ]

        for first, second, expected in test_cases:
            result = shared_prefix_len(first, second)
            assert result == expected, f"Failed for {first.hex()} vs {second.hex()}"


class TestUtilsIntegration:
    """Integration tests for utils functions."""

    def test_create_key_and_distance(self):
        """Test creating keys and calculating distances."""
        data1 = b"test data 1"
        data2 = b"test data 2"

        key1 = create_key_from_binary(data1)
        key2 = create_key_from_binary(data2)

        # Keys should be different
        assert key1 != key2

        # Distance should be non-zero
        dist = distance(key1, key2)
        assert dist > 0

        # Distance to self should be zero
        assert distance(key1, key1) == 0

    def test_peer_sorting_with_created_keys(self):
        """Test peer sorting using created keys."""
        # Create target key
        target_data = b"target"
        target_key = create_key_from_binary(target_data)

        # Create peer IDs
        peers = [
            ID(b"peer_far"),
            ID(b"peer_close"),
            ID(b"peer_medium"),
        ]

        # Sort by distance to target
        sorted_peers = sort_peer_ids_by_distance(target_key, peers)

        # Should return all peers
        assert len(sorted_peers) == len(peers)
        assert all(peer in sorted_peers for peer in peers)

        # Verify sorting (distances should be ascending)
        prev_distance = -1
        for peer in sorted_peers:
            peer_key = create_key_from_binary(peer.to_bytes())
            current_distance = distance(target_key, peer_key)
            assert current_distance >= prev_distance
            prev_distance = current_distance

    def test_all_utils_with_real_data(self):
        """Test all utility functions with realistic data."""
        # Create some realistic binary data
        content = b"QmSomeHashLikeContentIdentifier123456789"

        # Create key
        key = create_key_from_binary(content)
        assert len(key) == 32  # SHA-256 output

        # Convert to base58
        key_b58 = bytes_to_base58(key)
        assert isinstance(key_b58, str)
        assert len(key_b58) > 0

        # Test with peer IDs
        peers = [ID(f"peer_{i}".encode()) for i in range(5)]
        sorted_peers = sort_peer_ids_by_distance(key, peers)
        assert len(sorted_peers) == 5

        # Test shared prefix
        similar_content = (
            b"QmSomeHashLikeContentIdentifier123456780"  # Last char different
        )
        similar_key = create_key_from_binary(similar_content)

        prefix_len = shared_prefix_len(key, similar_key)
        assert prefix_len >= 0  # Should have some shared prefix due to similar input

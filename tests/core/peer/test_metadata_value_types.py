import json

import pytest

from libp2p.peer.id import ID
from libp2p.peer.peerdata import PeerData, PeerDataError
from libp2p.peer.peerstore import PeerStore, PeerStoreError


class TestMetadataValueTypeSafety:
    """Test suite for MetadataValue type safety and constraints."""

    def test_valid_metadata_types(self):
        """Test that all valid MetadataValue types are accepted."""
        peer_data = PeerData()

        # Test all valid types defined in MetadataValue
        valid_values = [
            ("string", "test string"),
            ("integer", 42),
            ("negative_int", -10),
            ("zero", 0),
            ("float", 3.14159),
            ("negative_float", -2.71),
            ("boolean_true", True),
            ("boolean_false", False),
            ("empty_list", []),
            ("string_list", ["item1", "item2", "item3"]),
            ("mixed_list", [1, "two", 3.0, True, None]),
            ("nested_list", [[1, 2], ["a", "b"]]),
            ("empty_dict", {}),
            ("simple_dict", {"key": "value"}),
            ("nested_dict", {"outer": {"inner": "value"}}),
            (
                "complex_dict",
                {"str": "value", "num": 42, "bool": True, "list": [1, 2], "null": None},
            ),
            ("none_value", None),
        ]

        for key, value in valid_values:
            peer_data.put_metadata(key, value)
            retrieved = peer_data.get_metadata(key)
            assert retrieved == value, (
                f"Failed for {key}: expected {value}, got {retrieved}"
            )

    def test_json_serialization_compatibility(self):
        """Test that all MetadataValue types are JSON serializable."""
        peer_data = PeerData()

        test_cases = [
            ("string_val", "hello world"),
            ("int_val", 123),
            ("float_val", 45.67),
            ("bool_val", True),
            ("list_val", [1, "two", 3.0, False]),
            ("dict_val", {"name": "test", "count": 5, "active": True}),
            ("null_val", None),
            (
                "complex_structure",
                {
                    "users": [
                        {"id": 1, "name": "Alice", "scores": [85.5, 92.0]},
                        {"id": 2, "name": "Bob", "scores": [78.0, 89.5]},
                    ],
                    "metadata": {"created": "2023", "version": 2},
                },
            ),
        ]

        for key, value in test_cases:
            # Store the value
            peer_data.put_metadata(key, value)
            retrieved = peer_data.get_metadata(key)

            # Test JSON serialization roundtrip
            json_str = json.dumps(retrieved)
            deserialized = json.loads(json_str)
            assert deserialized == retrieved, f"JSON roundtrip failed for {key}"
            assert deserialized == value, f"Original value not preserved for {key}"

    def test_peerstore_metadata_operations(self):
        """Test MetadataValue type safety through PeerStore interface."""
        peerstore = PeerStore()
        peer_id = ID.from_base58("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")

        # Test various metadata types through peerstore
        metadata_tests = [
            ("service_port", 8080),
            ("service_name", "libp2p-node"),
            ("is_relay", True),
            ("supported_protocols", ["gossipsub", "kad-dht"]),
            ("config", {"timeout": 30, "max_connections": 100}),
            ("last_seen", None),
        ]

        for key, value in metadata_tests:
            # Test put operation
            peerstore.put(peer_id, key, value)

            # Test get operation
            retrieved = peerstore.get(peer_id, key)
            assert retrieved == value, (
                f"PeerStore failed for {key}: expected {value}, got {retrieved}"
            )

            # Test JSON serializability
            json_str = json.dumps(retrieved)
            deserialized = json.loads(json_str)
            assert deserialized == value, f"PeerStore JSON roundtrip failed for {key}"

    def test_metadata_error_handling(self):
        """Test proper error handling for metadata operations."""
        peer_data = PeerData()

        # Test accessing non-existent key
        with pytest.raises(PeerDataError, match="key not found"):
            peer_data.get_metadata("non_existent_key")

        # Test PeerStore error handling
        peerstore = PeerStore()
        non_existent_peer = ID.from_base58(
            "QmNonExistentPeer1234567890123456789012345678"
        )

        with pytest.raises(PeerStoreError, match="peer ID not found"):
            peerstore.get(non_existent_peer, "any_key")

    def test_metadata_clearing(self):
        """Test metadata clearing operations."""
        peer_data = PeerData()

        # Add some metadata
        peer_data.put_metadata("key1", "value1")
        peer_data.put_metadata("key2", 42)
        peer_data.put_metadata("key3", {"nested": "dict"})

        # Verify metadata exists
        assert peer_data.get_metadata("key1") == "value1"
        assert peer_data.get_metadata("key2") == 42
        assert peer_data.get_metadata("key3") == {"nested": "dict"}

        # Clear metadata
        peer_data.clear_metadata()

        # Verify all metadata is cleared
        with pytest.raises(PeerDataError):
            peer_data.get_metadata("key1")
        with pytest.raises(PeerDataError):
            peer_data.get_metadata("key2")
        with pytest.raises(PeerDataError):
            peer_data.get_metadata("key3")

    def test_metadata_overwrite(self):
        """Test that metadata values can be overwritten with different types."""
        peer_data = PeerData()
        key = "dynamic_key"

        # Test type changes
        type_progression = [
            "initial_string",
            42,
            [1, 2, 3],
            {"dict": "value"},
            True,
            None,
        ]

        for value in type_progression:
            peer_data.put_metadata(key, value)
            retrieved = peer_data.get_metadata(key)
            assert retrieved == value, f"Overwrite failed for value {value}"

    def test_edge_case_values(self):
        """Test edge cases for MetadataValue types."""
        peer_data = PeerData()

        edge_cases = [
            ("empty_string", ""),
            ("zero_int", 0),
            ("zero_float", 0.0),
            ("negative_zero", -0.0),
            ("max_int", 2**63 - 1),  # Large integer
            ("min_int", -(2**63)),  # Large negative integer
            ("unicode_string", "Hello 世界 🌍"),
            ("special_chars", "!@#$%^&*()_+-=[]{}|;:,.<>?"),
            ("deeply_nested", {"a": {"b": {"c": {"d": [1, 2, {"e": "deep"}]}}}}),
            ("boolean_in_containers", [True, False, {"flag": True}]),
        ]

        for key, value in edge_cases:
            peer_data.put_metadata(key, value)
            retrieved = peer_data.get_metadata(key)
            assert retrieved == value, f"Edge case failed for {key}"

            # Ensure JSON serialization works
            json_str = json.dumps(retrieved)
            deserialized = json.loads(json_str)
            assert deserialized == value, f"Edge case JSON failed for {key}"

    def test_type_annotation_compliance(self):
        """Test that the metadata field type annotation is correct."""
        peer_data = PeerData()

        # Verify the metadata field has the correct type annotation
        assert hasattr(peer_data, "metadata")
        assert isinstance(peer_data.metadata, dict)

        # Test that we can store various MetadataValue types
        peer_data.metadata["direct_access"] = "test"
        assert peer_data.metadata["direct_access"] == "test"

        # Test mixed types in the same metadata dict
        peer_data.metadata.update(
            {
                "str_key": "string",
                "int_key": 123,
                "bool_key": True,
                "list_key": [1, 2, 3],
                "dict_key": {"nested": "value"},
                "none_key": None,
            }
        )

        # Verify all values are accessible and correct
        assert peer_data.metadata["str_key"] == "string"
        assert peer_data.metadata["int_key"] == 123
        assert peer_data.metadata["bool_key"] is True
        assert peer_data.metadata["list_key"] == [1, 2, 3]
        assert peer_data.metadata["dict_key"] == {"nested": "value"}
        assert peer_data.metadata["none_key"] is None


class TestInvalidMetadataTypes:
    """Test that invalid types would cause issues (mainly for documentation)."""

    def test_non_json_serializable_types(self):
        """Test that non-JSON-serializable types cause serialization errors."""
        peer_data = PeerData()

        # These types are not in MetadataValue but might be passed at runtime
        # They should work for storage but fail during JSON serialization
        problematic_values = [
            ("set_type", {1, 2, 3}),  # set is not JSON serializable
            ("tuple_type", (1, 2, 3)),  # tuple is not JSON serializable
            # complex numbers not JSON serializable
            ("complex_type", complex(1, 2)),
            ("bytes_type", b"binary data"),  # bytes not JSON serializable
        ]

        for key, value in problematic_values:
            # These might work at runtime (Python is dynamically typed)
            # but they violate the MetadataValue type constraint
            peer_data.put_metadata(key, value)  # This works at runtime
            retrieved = peer_data.get_metadata(key)
            assert retrieved == value  # This also works

            # But JSON serialization should fail
            with pytest.raises(TypeError):
                json.dumps(retrieved)

    def test_custom_object_serialization(self):
        """Test that custom objects cause serialization issues."""
        peer_data = PeerData()

        class CustomObject:
            def __init__(self, value):
                self.value = value

        custom_obj = CustomObject("test")

        # This works at runtime (no static type checking)
        peer_data.put_metadata("custom", custom_obj)
        retrieved = peer_data.get_metadata("custom")
        assert retrieved is custom_obj

        # But JSON serialization fails
        with pytest.raises(TypeError):
            json.dumps(retrieved)


# Integration test to verify the fix works end-to-end
class TestMetadataValueIntegration:
    """Integration tests for the complete metadata system."""

    def test_complete_peer_lifecycle(self):
        """Test complete peer lifecycle with metadata operations."""
        peerstore = PeerStore()
        peer_id = ID.from_base58("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")

        # Add various metadata throughout peer lifecycle
        initial_metadata = {
            "node_type": "relay",
            "version": "v0.1.0",
            "capabilities": ["relay", "kad-dht", "gossipsub"],
            "config": {"max_connections": 100, "timeout": 30.0, "enable_logging": True},
            "stats": {"uptime": 3600, "messages_relayed": 1500, "connections": 25},
        }

        # Store all metadata
        for key, value in initial_metadata.items():
            peerstore.put(peer_id, key, value)

        # Verify all metadata is retrievable and JSON serializable
        for key, expected_value in initial_metadata.items():
            retrieved = peerstore.get(peer_id, key)
            assert retrieved == expected_value

            # Test JSON serialization
            json_str = json.dumps(retrieved)
            deserialized = json.loads(json_str)
            assert deserialized == expected_value

        # Test metadata updates
        peerstore.put(
            peer_id,
            "stats",
            {"uptime": 7200, "messages_relayed": 3000, "connections": 30},
        )
        updated_stats = peerstore.get(peer_id, "stats")
        assert updated_stats["uptime"] == 7200
        assert updated_stats["messages_relayed"] == 3000

        # Test metadata clearing
        peerstore.clear_metadata(peer_id)

        # Verify metadata is cleared
        with pytest.raises(PeerStoreError):
            peerstore.get(peer_id, "node_type")

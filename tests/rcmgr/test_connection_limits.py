"""
Comprehensive tests for ConnectionLimits component.

Tests the connection limits configuration and enforcement logic
that mirrors the Rust libp2p connection limits functionality.
"""


import pytest

from libp2p.rcmgr.connection_limits import (
    ConnectionLimits,
    new_connection_limits_with_defaults,
)
from libp2p.rcmgr.exceptions import ResourceLimitExceeded


class TestConnectionLimits:
    """Test suite for ConnectionLimits class."""

    def test_default_connection_limits(self) -> None:
        """Test default connection limits creation."""
        limits = new_connection_limits_with_defaults()

        assert limits.max_pending_inbound == 64
        assert limits.max_pending_outbound == 64
        assert limits.max_established_inbound == 256
        assert limits.max_established_outbound == 256
        assert limits.max_established_per_peer == 8
        assert limits.max_established_total == 1024

    def test_custom_connection_limits(self) -> None:
        """Test custom connection limits creation."""
        limits = ConnectionLimits(
            max_pending_inbound=10,
            max_pending_outbound=20,
            max_established_inbound=30,
            max_established_outbound=40,
            max_established_per_peer=5,
            max_established_total=100,
        )

        assert limits.max_pending_inbound == 10
        assert limits.max_pending_outbound == 20
        assert limits.max_established_inbound == 30
        assert limits.max_established_outbound == 40
        assert limits.max_established_per_peer == 5
        assert limits.max_established_total == 100

    def test_with_max_pending_inbound(self) -> None:
        """Test fluent configuration for pending inbound limit."""
        limits = ConnectionLimits().with_max_pending_inbound(50)
        assert limits.max_pending_inbound == 50

    def test_with_max_pending_outbound(self) -> None:
        """Test fluent configuration for pending outbound limit."""
        limits = ConnectionLimits().with_max_pending_outbound(75)
        assert limits.max_pending_outbound == 75

    def test_with_max_established_inbound(self) -> None:
        """Test fluent configuration for established inbound limit."""
        limits = ConnectionLimits().with_max_established_inbound(100)
        assert limits.max_established_inbound == 100

    def test_with_max_established_outbound(self) -> None:
        """Test fluent configuration for established outbound limit."""
        limits = ConnectionLimits().with_max_established_outbound(150)
        assert limits.max_established_outbound == 150

    def test_with_max_established_per_peer(self) -> None:
        """Test fluent configuration for per-peer limit."""
        limits = ConnectionLimits().with_max_established_per_peer(10)
        assert limits.max_established_per_peer == 10

    def test_with_max_established_total(self) -> None:
        """Test fluent configuration for total limit."""
        limits = ConnectionLimits().with_max_established_total(500)
        assert limits.max_established_total == 500

    def test_chained_configuration(self) -> None:
        """Test chaining multiple configuration methods."""
        limits = (ConnectionLimits()
                 .with_max_pending_inbound(10)
                 .with_max_pending_outbound(20)
                 .with_max_established_inbound(30)
                 .with_max_established_outbound(40)
                 .with_max_established_per_peer(5)
                 .with_max_established_total(100))

        assert limits.max_pending_inbound == 10
        assert limits.max_pending_outbound == 20
        assert limits.max_established_inbound == 30
        assert limits.max_established_outbound == 40
        assert limits.max_established_per_peer == 5
        assert limits.max_established_total == 100

    def test_check_pending_inbound_limit_within_limit(self) -> None:
        """Test pending inbound limit check when within limit."""
        limits = ConnectionLimits(max_pending_inbound=5)

        # Should not raise exception
        limits.check_pending_inbound_limit(3)

    def test_check_pending_inbound_limit_exceeds_limit(self) -> None:
        """Test pending inbound limit check when exceeding limit."""
        limits = ConnectionLimits(max_pending_inbound=5)

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            limits.check_pending_inbound_limit(6)

        assert "pending inbound" in str(exc_info.value).lower()
        assert "6" in str(exc_info.value)
        assert "5" in str(exc_info.value)

    def test_check_pending_outbound_limit_within_limit(self) -> None:
        """Test pending outbound limit check when within limit."""
        limits = ConnectionLimits(max_pending_outbound=5)

        # Should not raise exception
        limits.check_pending_outbound_limit(3)

    def test_check_pending_outbound_limit_exceeds_limit(self) -> None:
        """Test pending outbound limit check when exceeding limit."""
        limits = ConnectionLimits(max_pending_outbound=5)

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            limits.check_pending_outbound_limit(6)

        assert "pending outbound" in str(exc_info.value).lower()
        assert "6" in str(exc_info.value)
        assert "5" in str(exc_info.value)

    def test_check_established_inbound_limit_within_limit(self) -> None:
        """Test established inbound limit check when within limit."""
        limits = ConnectionLimits(max_established_inbound=10)

        # Should not raise exception
        limits.check_established_inbound_limit(8)

    def test_check_established_inbound_limit_exceeds_limit(self) -> None:
        """Test established inbound limit check when exceeding limit."""
        limits = ConnectionLimits(max_established_inbound=10)

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            limits.check_established_inbound_limit(11)

        assert "established inbound" in str(exc_info.value).lower()
        assert "11" in str(exc_info.value)
        assert "10" in str(exc_info.value)

    def test_check_established_outbound_limit_within_limit(self) -> None:
        """Test established outbound limit check when within limit."""
        limits = ConnectionLimits(max_established_outbound=10)

        # Should not raise exception
        limits.check_established_outbound_limit(8)

    def test_check_established_outbound_limit_exceeds_limit(self) -> None:
        """Test established outbound limit check when exceeding limit."""
        limits = ConnectionLimits(max_established_outbound=10)

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            limits.check_established_outbound_limit(11)

        assert "established outbound" in str(exc_info.value).lower()
        assert "11" in str(exc_info.value)
        assert "10" in str(exc_info.value)

    def test_check_established_per_peer_limit_within_limit(self) -> None:
        """Test per-peer limit check when within limit."""
        limits = ConnectionLimits(max_established_per_peer=5)

        # Should not raise exception
        limits.check_established_per_peer_limit(3)

    def test_check_established_per_peer_limit_exceeds_limit(self) -> None:
        """Test per-peer limit check when exceeding limit."""
        limits = ConnectionLimits(max_established_per_peer=5)

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            limits.check_established_per_peer_limit(6)

        assert "per peer" in str(exc_info.value).lower()
        assert "6" in str(exc_info.value)
        assert "5" in str(exc_info.value)

    def test_check_established_total_limit_within_limit(self) -> None:
        """Test total limit check when within limit."""
        limits = ConnectionLimits(max_established_total=100)

        # Should not raise exception
        limits.check_established_total_limit(80)

    def test_check_established_total_limit_exceeds_limit(self) -> None:
        """Test total limit check when exceeding limit."""
        limits = ConnectionLimits(max_established_total=100)

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            limits.check_established_total_limit(101)

        assert "total" in str(exc_info.value).lower()
        assert "101" in str(exc_info.value)
        assert "100" in str(exc_info.value)

    def test_zero_limits(self) -> None:
        """Test behavior with zero limits."""
        limits = ConnectionLimits(
            max_pending_inbound=0,
            max_pending_outbound=0,
            max_established_inbound=0,
            max_established_outbound=0,
            max_established_per_peer=0,
            max_established_total=0,
        )

        # All checks should fail with zero limits
        with pytest.raises(ResourceLimitExceeded):
            limits.check_pending_inbound_limit(1)

        with pytest.raises(ResourceLimitExceeded):
            limits.check_pending_outbound_limit(1)

        with pytest.raises(ResourceLimitExceeded):
            limits.check_established_inbound_limit(1)

        with pytest.raises(ResourceLimitExceeded):
            limits.check_established_outbound_limit(1)

        with pytest.raises(ResourceLimitExceeded):
            limits.check_established_per_peer_limit(1)

        with pytest.raises(ResourceLimitExceeded):
            limits.check_established_total_limit(1)

    def test_very_high_limits(self) -> None:
        """Test behavior with very high limits."""
        limits = ConnectionLimits(
            max_pending_inbound=1000000,
            max_pending_outbound=1000000,
            max_established_inbound=1000000,
            max_established_outbound=1000000,
            max_established_per_peer=1000000,
            max_established_total=1000000,
        )

        # All checks should pass with very high limits
        limits.check_pending_inbound_limit(999999)
        limits.check_pending_outbound_limit(999999)
        limits.check_established_inbound_limit(999999)
        limits.check_established_outbound_limit(999999)
        limits.check_established_per_peer_limit(999999)
        limits.check_established_total_limit(999999)

    def test_limits_equality(self) -> None:
        """Test limits equality comparison."""
        limits1 = ConnectionLimits(max_pending_inbound=10)
        limits2 = ConnectionLimits(max_pending_inbound=10)
        limits3 = ConnectionLimits(max_pending_inbound=20)

        assert limits1 == limits2
        assert limits1 != limits3

    def test_limits_string_representation(self) -> None:
        """Test string representation of limits."""
        limits = ConnectionLimits(
            max_pending_inbound=10,
            max_pending_outbound=20,
            max_established_inbound=30,
            max_established_outbound=40,
            max_established_per_peer=5,
            max_established_total=100,
        )

        str_repr = str(limits)
        assert "10" in str_repr  # pending inbound
        assert "20" in str_repr  # pending outbound
        assert "30" in str_repr  # established inbound
        assert "40" in str_repr  # established outbound
        assert "5" in str_repr   # per peer
        assert "100" in str_repr # total

    def test_limits_repr(self) -> None:
        """Test repr representation of limits."""
        limits = ConnectionLimits(max_pending_inbound=10)
        repr_str = repr(limits)

        assert "ConnectionLimits" in repr_str
        assert "max_pending_inbound=10" in repr_str

    def test_limits_hash(self) -> None:
        """Test limits hash functionality."""
        limits1 = ConnectionLimits(max_pending_inbound=10)
        limits2 = ConnectionLimits(max_pending_inbound=10)
        limits3 = ConnectionLimits(max_pending_inbound=20)

        assert hash(limits1) == hash(limits2)
        assert hash(limits1) != hash(limits3)

    def test_limits_in_set(self) -> None:
        """Test limits can be used in sets."""
        limits1 = ConnectionLimits(max_pending_inbound=10)
        limits2 = ConnectionLimits(max_pending_inbound=10)
        limits3 = ConnectionLimits(max_pending_inbound=20)

        limits_set = {limits1, limits2, limits3}
        assert len(limits_set) == 2  # limits1 and limits2 are equal

    def test_limits_in_dict(self) -> None:
        """Test limits can be used as dictionary keys."""
        limits1 = ConnectionLimits(max_pending_inbound=10)
        limits2 = ConnectionLimits(max_pending_inbound=20)

        limits_dict = {limits1: "value1", limits2: "value2"}
        assert limits_dict[limits1] == "value1"
        assert limits_dict[limits2] == "value2"

    def test_limits_copy(self) -> None:
        """Test limits can be copied."""
        import copy

        limits = ConnectionLimits(max_pending_inbound=10)
        limits_copy = copy.copy(limits)

        assert limits == limits_copy
        assert limits is not limits_copy

    def test_limits_deep_copy(self) -> None:
        """Test limits can be deep copied."""
        import copy

        limits = ConnectionLimits(max_pending_inbound=10)
        limits_deep_copy = copy.deepcopy(limits)

        assert limits == limits_deep_copy
        assert limits is not limits_deep_copy

    def test_limits_immutability_after_creation(self) -> None:
        """Test that limits are immutable after creation."""
        limits = ConnectionLimits(max_pending_inbound=10)

        # Attempting to modify should not change the original
        limits.with_max_pending_inbound(20)
        assert limits.max_pending_inbound == 10  # Original unchanged

    def test_limits_validation_edge_cases(self) -> None:
        """Test limits validation with edge case values."""
        # Test with negative values (should be handled gracefully)
        limits = ConnectionLimits(max_pending_inbound=-1)

        # Should not raise exception during creation
        assert limits.max_pending_inbound == -1

        # But should raise exception when checking limits
        with pytest.raises(ResourceLimitExceeded):
            limits.check_pending_inbound_limit(0)

    def test_limits_with_none_values(self) -> None:
        """Test limits with None values (should use defaults)."""
        limits = ConnectionLimits()

        # Should have default values
        assert limits.max_pending_inbound is not None
        assert limits.max_pending_outbound is not None
        assert limits.max_established_inbound is not None
        assert limits.max_established_outbound is not None
        assert limits.max_established_per_peer is not None
        assert limits.max_established_total is not None

    def test_limits_performance(self) -> None:
        """Test limits performance with many checks."""
        limits = ConnectionLimits(max_established_total=1000)

        # Should handle many checks efficiently
        for i in range(1000):
            limits.check_established_total_limit(i)

        # Should fail on the 1001st check
        with pytest.raises(ResourceLimitExceeded):
            limits.check_established_total_limit(1001)

    def test_limits_concurrent_access(self) -> None:
        """Test limits with concurrent access."""
        import threading

        limits = ConnectionLimits(max_established_total=100)
        results = []
        errors = []

        def check_limit(value):
            try:
                limits.check_established_total_limit(value)
                results.append(value)
            except ResourceLimitExceeded as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=check_limit, args=(i * 10,))
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All should succeed (10 * 10 = 100, which is the limit)
        assert len(results) == 10
        assert len(errors) == 0

    def test_limits_memory_usage(self) -> None:
        """Test limits memory usage with many instances."""
        # Create many limits instances
        limits_list = []
        for i in range(1000):
            limits = ConnectionLimits(max_established_total=i)
            limits_list.append(limits)

        # All should be accessible
        assert len(limits_list) == 1000
        assert limits_list[0].max_established_total == 0
        assert limits_list[999].max_established_total == 999

    def test_limits_serialization(self) -> None:
        """Test limits can be serialized/deserialized."""
        import json

        limits = ConnectionLimits(max_pending_inbound=10)

        # Convert to dict for serialization
        limits_dict = {
            "max_pending_inbound": limits.max_pending_inbound,
            "max_pending_outbound": limits.max_pending_outbound,
            "max_established_inbound": limits.max_established_inbound,
            "max_established_outbound": limits.max_established_outbound,
            "max_established_per_peer": limits.max_established_per_peer,
            "max_established_total": limits.max_established_total,
        }

        # Should be serializable
        json_str = json.dumps(limits_dict)
        assert json_str is not None

        # Should be deserializable
        deserialized = json.loads(json_str)
        assert deserialized["max_pending_inbound"] == 10

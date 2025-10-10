"""
Tests for resource manager scopes.
"""

import pytest

from libp2p.peer.id import ID
from libp2p.rcmgr.exceptions import (
    MemoryLimitExceeded,
    ResourceScopeClosed,
    StreamOrConnLimitExceeded,
)
from libp2p.rcmgr.limits import BaseLimit, Direction
from libp2p.rcmgr.metrics import Metrics
from libp2p.rcmgr.scope import (
    BaseResourceScope,
    PeerScope,
    Resources,
    SystemScope,
    TransientScope,
)


def test_resources_memory_management():
    """Test memory reservation and release in Resources."""
    limit = BaseLimit(memory=1024)
    resources = Resources(limit)

    # Test memory addition
    resources.add_memory(512)
    assert resources.memory == 512

    # Test memory removal
    resources.remove_memory(256)
    assert resources.memory == 256

    # Test memory removal with underflow protection
    resources.remove_memory(1000)
    assert resources.memory == 0


def test_resources_memory_limits():
    """Test memory limit checking."""
    limit = BaseLimit(memory=1024)
    resources = Resources(limit)

    # Should succeed
    resources.check_memory(512)

    # Should fail - exceeds limit
    with pytest.raises(MemoryLimitExceeded):
        resources.check_memory(2048)


def test_resources_memory_priority():
    """Test memory reservation with priority."""
    limit = BaseLimit(memory=1024)
    resources = Resources(limit)

    # High priority (255) should almost always succeed
    resources.check_memory(1020, priority=255)

    # Low priority (1) should fail more easily
    with pytest.raises(MemoryLimitExceeded):
        resources.check_memory(1020, priority=1)


def test_resources_stream_management():
    """Test stream addition and removal."""
    limit = BaseLimit(
        streams=10,
        streams_inbound=6,
        streams_outbound=4
    )
    resources = Resources(limit)

    # Add inbound streams
    resources.add_stream(Direction.INBOUND)
    assert resources.streams_inbound == 1
    assert resources.streams_outbound == 0

    # Add outbound streams
    resources.add_stream(Direction.OUTBOUND)
    assert resources.streams_inbound == 1
    assert resources.streams_outbound == 1

    # Remove streams
    resources.remove_stream(Direction.INBOUND)
    assert resources.streams_inbound == 0
    assert resources.streams_outbound == 1


def test_resources_stream_limits():
    """Test stream limit checking."""
    limit = BaseLimit(
        streams=2,
        streams_inbound=1,
        streams_outbound=1
    )
    resources = Resources(limit)

    # First inbound stream should succeed
    resources.check_streams(Direction.INBOUND)
    resources.add_stream(Direction.INBOUND)

    # Second inbound stream should fail
    with pytest.raises(StreamOrConnLimitExceeded) as exc_info:
        resources.check_streams(Direction.INBOUND)
    assert "streams_inbound" in str(exc_info.value)

    # First outbound stream should succeed
    resources.check_streams(Direction.OUTBOUND)
    resources.add_stream(Direction.OUTBOUND)

    # Second outbound stream should fail (total limit)
    with pytest.raises(StreamOrConnLimitExceeded) as exc_info:
        resources.check_streams(Direction.OUTBOUND)
    assert "streams_total" in str(exc_info.value)


def test_resources_connection_management():
    """Test connection addition and removal."""
    limit = BaseLimit(
        conns=10,
        conns_inbound=6,
        conns_outbound=4,
        fd=5
    )
    resources = Resources(limit)

    # Add connections with FD
    resources.add_conn(Direction.INBOUND, use_fd=True)
    assert resources.conns_inbound == 1
    assert resources.num_fd == 1

    # Add connection without FD
    resources.add_conn(Direction.OUTBOUND, use_fd=False)
    assert resources.conns_outbound == 1
    assert resources.num_fd == 1  # Should not change

    # Remove connections
    resources.remove_conn(Direction.INBOUND, use_fd=True)
    assert resources.conns_inbound == 0
    assert resources.num_fd == 0


def test_resources_connection_limits():
    """Test connection limit checking."""
    limit = BaseLimit(
        conns=1,
        conns_inbound=1,
        conns_outbound=1,
        fd=1
    )
    resources = Resources(limit)

    # First connection should succeed
    resources.check_conns(Direction.INBOUND, use_fd=True)
    resources.add_conn(Direction.INBOUND, use_fd=True)

    # Second connection should fail (FD limit)
    with pytest.raises(StreamOrConnLimitExceeded) as exc_info:
        resources.check_conns(Direction.OUTBOUND, use_fd=True)
    assert "fd" in str(exc_info.value)


def test_base_resource_scope_memory():
    """Test memory management in BaseResourceScope."""
    limit = BaseLimit(memory=1024)
    scope = BaseResourceScope(limit, name="test")

    # Reserve memory
    scope.reserve_memory(512)
    assert scope.resources.memory == 512

    # Release memory
    scope.release_memory(256)
    assert scope.resources.memory == 256

    # Clean up
    scope.done()


def test_base_resource_scope_memory_limit():
    """Test memory limit enforcement."""
    limit = BaseLimit(memory=1024)
    scope = BaseResourceScope(limit, name="test")

    # Should fail - exceeds limit
    with pytest.raises(MemoryLimitExceeded):
        scope.reserve_memory(2048)

    scope.done()


def test_base_resource_scope_streams():
    """Test stream management in BaseResourceScope."""
    limit = BaseLimit(
        streams=2,
        streams_inbound=1,
        streams_outbound=1
    )
    scope = BaseResourceScope(limit, name="test")

    # Add streams
    scope.add_stream(Direction.INBOUND)
    scope.add_stream(Direction.OUTBOUND)

    # Check stats
    stats = scope.stat()
    assert stats.num_streams_inbound == 1
    assert stats.num_streams_outbound == 1

    # Remove streams
    scope.remove_stream(Direction.INBOUND)
    stats = scope.stat()
    assert stats.num_streams_inbound == 0

    scope.done()


def test_base_resource_scope_hierarchical():
    """Test hierarchical resource management."""
    # Create parent scope
    parent_limit = BaseLimit(memory=1024)
    parent = BaseResourceScope(parent_limit, name="parent")

    # Create child scope
    child_limit = BaseLimit(memory=512)
    child = BaseResourceScope(child_limit, edges=[parent], name="child")

    # Reserve memory in child - should check both scopes
    child.reserve_memory(256)
    assert child.resources.memory == 256
    assert parent.resources.memory == 256

    # Try to exceed parent limit
    with pytest.raises(MemoryLimitExceeded):
        child.reserve_memory(1000)  # Would exceed parent limit

    # Clean up
    child.done()
    parent.done()


def test_scope_closure():
    """Test scope closure behavior."""
    limit = BaseLimit(memory=1024)
    scope = BaseResourceScope(limit, name="test")

    # Close the scope
    scope.done()

    # Operations should fail after closure
    with pytest.raises(ResourceScopeClosed):
        scope.reserve_memory(512)

    with pytest.raises(ResourceScopeClosed):
        scope.add_stream(Direction.INBOUND)


def test_system_scope():
    """Test SystemScope creation and behavior."""
    limit = BaseLimit(memory=1024)
    metrics = Metrics()

    system = SystemScope(limit, metrics)
    assert system.name == "system"
    assert len(system.edges) == 0  # No parent scopes

    # Should work normally
    system.reserve_memory(512)
    assert system.resources.memory == 512

    system.done()


def test_transient_scope():
    """Test TransientScope creation and behavior."""
    system_limit = BaseLimit(memory=2048)
    system = SystemScope(system_limit)

    transient_limit = BaseLimit(memory=1024)
    transient = TransientScope(transient_limit, system)

    assert transient.name == "transient"
    assert len(transient.edges) == 1
    assert transient.edges[0] == system

    # Reserve memory - should affect both scopes
    transient.reserve_memory(512)
    assert transient.resources.memory == 512
    assert system.resources.memory == 512

    transient.done()
    system.done()


def test_peer_scope():
    """Test PeerScope creation and behavior."""
    system_limit = BaseLimit(memory=2048)
    system = SystemScope(system_limit)

    peer_id = ID(b"test_peer")
    peer_limit = BaseLimit(memory=1024)
    peer = PeerScope(peer_id, peer_limit, system)

    assert f"peer:{peer_id}" in peer.name
    assert peer.peer_id == peer_id
    assert len(peer.edges) == 1
    assert peer.edges[0] == system

    peer.done()
    system.done()


def test_metrics_integration():
    """Test metrics integration with scopes."""
    limit = BaseLimit(memory=1024)
    metrics = Metrics()
    scope = BaseResourceScope(limit, metrics=metrics, name="test")

    # Memory operations should be recorded
    scope.reserve_memory(512)
    summary = metrics.get_summary()
    assert summary["resource_metrics"]["memory"]["allowed"] == 1

    # Stream operations should be recorded
    scope.add_stream(Direction.INBOUND)
    summary = metrics.get_summary()
    assert summary["resource_metrics"]["streams_inbound"]["allowed"] == 1

    scope.done()

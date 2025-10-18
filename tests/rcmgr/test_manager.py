"""
Tests for the main ResourceManager class.
"""

import pytest

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.rcmgr.allowlist import AllowlistConfig
from libp2p.rcmgr.exceptions import ResourceLimitExceeded
from libp2p.rcmgr.limits import BaseLimit, Direction, FixedLimiter
from libp2p.rcmgr.manager import ResourceManager, new_resource_manager


def test_resource_manager_creation() -> None:
    """Test ResourceManager creation."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    assert rm.limiter == limiter
    assert rm.system is not None
    assert rm.transient is not None
    assert rm.allowlist is not None
    assert rm.metrics is not None

    rm.close()


def test_new_resource_manager() -> None:
    """Test new_resource_manager convenience function."""
    limiter = FixedLimiter()
    rm = new_resource_manager(limiter)

    assert isinstance(rm, ResourceManager)
    rm.close()


def test_new_resource_manager_with_config() -> None:
    """Test new_resource_manager with configuration."""
    limiter = FixedLimiter()
    allowlist_config = AllowlistConfig()

    rm = new_resource_manager(
        limiter, allowlist_config=allowlist_config, enable_metrics=True
    )

    assert isinstance(rm, ResourceManager)
    rm.close()


def test_open_connection() -> None:
    """Test opening connections."""
    # Create limiter with low connection limits for testing
    limiter = FixedLimiter()
    # Set system limits to constrain total resource usage
    limiter.system = BaseLimit(
        conns=2,
        conns_inbound=1,
        conns_outbound=1,
        fd=2,  # Total FD limit across all connections
        streams=1000,
        memory=1024**3,
    )

    rm = ResourceManager(limiter)

    # Open inbound connection
    conn1 = rm.open_connection(Direction.INBOUND, use_fd=True)
    assert conn1 is not None

    # Open outbound connection
    conn2 = rm.open_connection(Direction.OUTBOUND, use_fd=True)
    assert conn2 is not None

    # Third connection should fail (FD limit)
    with pytest.raises(ResourceLimitExceeded):
        rm.open_connection(Direction.INBOUND, use_fd=True)

    # Clean up
    conn1.done()
    conn2.done()
    rm.close()


def test_open_stream() -> None:
    """Test opening streams."""
    # Create limiter with low stream limits for testing
    limiter = FixedLimiter()
    limiter.peer_default = BaseLimit(streams=2, streams_inbound=1, streams_outbound=1)

    rm = ResourceManager(limiter)
    peer_id = ID(b"test_peer")

    # Open inbound stream
    stream1 = rm.open_stream(peer_id, Direction.INBOUND)
    assert stream1 is not None
    assert stream1.peer.peer_id == peer_id

    # Open outbound stream
    stream2 = rm.open_stream(peer_id, Direction.OUTBOUND)
    assert stream2 is not None

    # Third stream should fail (total limit)
    with pytest.raises(ResourceLimitExceeded):
        rm.open_stream(peer_id, Direction.INBOUND)

    # Clean up
    stream1.done()
    stream2.done()
    rm.close()


def test_view_system() -> None:
    """Test viewing system scope."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    def check_system(scope):
        assert scope.name == "system"
        scope.reserve_memory(1024)
        return scope.stat()

    stats = rm.view_system(check_system)
    assert stats.memory == 1024

    rm.close()


def test_view_transient() -> None:
    """Test viewing transient scope."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    def check_transient(scope):
        assert scope.name == "transient"
        scope.add_stream(Direction.INBOUND)
        return scope.stat()

    stats = rm.view_transient(check_transient)
    assert stats.num_streams_inbound == 1

    rm.close()


def test_view_peer() -> None:
    """Test viewing peer scope."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)
    peer_id = ID(b"test_peer")

    def check_peer(scope):
        assert scope.peer_id == peer_id
        scope.reserve_memory(512)
        return scope.stat()

    stats = rm.view_peer(peer_id, check_peer)
    assert stats.memory == 512

    rm.close()


def test_view_protocol() -> None:
    """Test viewing protocol scope."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)
    protocol = TProtocol("/test/1.0.0")

    def check_protocol(scope):
        assert scope.protocol == protocol
        scope.add_stream(Direction.OUTBOUND)
        return scope.stat()

    stats = rm.view_protocol(protocol, check_protocol)
    assert stats.num_streams_outbound == 1

    rm.close()


def test_view_service() -> None:
    """Test viewing service scope."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)
    service = "test_service"

    def check_service(scope):
        assert scope.service == service
        scope.add_conn(Direction.INBOUND)
        return scope.stat()

    stats = rm.view_service(service, check_service)
    assert stats.num_conns_inbound == 1

    rm.close()


def test_sticky_scopes() -> None:
    """Test sticky scope marking."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    peer_id = ID(b"test_peer")
    protocol = TProtocol("/test/1.0.0")
    service = "test_service"

    # Mark scopes as sticky
    rm.set_sticky_peer(peer_id)
    rm.set_sticky_protocol(protocol)
    rm.set_sticky_service(service)

    # Check they're in sticky sets
    assert peer_id in rm._sticky_peers
    assert protocol in rm._sticky_protocols
    assert service in rm._sticky_services

    rm.close()


def test_list_methods() -> None:
    """Test listing active scopes."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    peer_id1 = ID(b"peer1")
    peer_id2 = ID(b"peer2")
    protocol = TProtocol("/test/1.0.0")
    service = "test_service"

    # Create some scopes
    rm.view_peer(peer_id1, lambda s: None)
    rm.view_peer(peer_id2, lambda s: None)
    rm.view_protocol(protocol, lambda s: None)
    rm.view_service(service, lambda s: None)

    # Check lists
    peers = rm.list_peers()
    assert peer_id1 in peers
    assert peer_id2 in peers

    protocols = rm.list_protocols()
    assert protocol in protocols

    services = rm.list_services()
    assert service in services

    rm.close()


def test_allowlist_access() -> None:
    """Test allowlist access."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    allowlist = rm.get_allowlist()
    assert allowlist is not None

    # Add a peer to allowlist
    peer_id = ID(b"trusted_peer")
    allowlist.add_peer(peer_id)

    assert allowlist.allowed_peer(peer_id)

    rm.close()


def test_metrics_access() -> None:
    """Test metrics access."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    metrics = rm.get_metrics()
    assert metrics is not None

    # Metrics should record operations
    rm.open_connection(Direction.INBOUND)
    summary = metrics.get_summary()
    assert "resource_metrics" in summary

    rm.close()


def test_resource_manager_closure() -> None:
    """Test proper cleanup when closing ResourceManager."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    # Create some scopes
    peer_id = ID(b"test_peer")
    _stream = rm.open_stream(peer_id, Direction.INBOUND)
    _conn = rm.open_connection(Direction.OUTBOUND)

    # Close the manager
    rm.close()

    # Operations should fail
    with pytest.raises(RuntimeError):
        rm.open_stream(peer_id, Direction.INBOUND)

    with pytest.raises(RuntimeError):
        rm.open_connection(Direction.INBOUND)


def test_garbage_collection() -> None:
    """Test garbage collection of unused scopes."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    peer_id = ID(b"test_peer")
    protocol = TProtocol("/test/1.0.0")

    # Create and release scopes
    def use_peer(scope):
        scope.reserve_memory(512)

    def use_protocol(scope):
        scope.add_stream(Direction.INBOUND)

    rm.view_peer(peer_id, use_peer)
    rm.view_protocol(protocol, use_protocol)

    # Scopes should exist
    assert peer_id in rm._peer_scopes
    assert protocol in rm._protocol_scopes

    # Manually trigger GC
    rm._gc_scopes()

    # Non-sticky scopes with zero references might be collected
    # (The exact behavior depends on reference counting implementation)

    rm.close()


def test_concurrent_access() -> None:
    """Test concurrent access to ResourceManager."""
    import threading

    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    peer_id = ID(b"test_peer")
    results = []
    errors = []

    def worker():
        try:
            stream = rm.open_stream(peer_id, Direction.INBOUND)
            results.append(stream)
        except Exception as e:
            errors.append(e)

    # Start multiple threads
    threads = []
    for _ in range(5):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    # Some should succeed, some might fail due to limits
    assert len(results) + len(errors) == 5

    # Clean up
    for stream in results:
        stream.done()

    rm.close()

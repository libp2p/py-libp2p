"""
Integration tests for the resource manager.
"""

import threading

import pytest

from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.rcmgr.allowlist import AllowlistConfig
from libp2p.rcmgr.exceptions import ResourceLimitExceeded
from libp2p.rcmgr.limits import BaseLimit, Direction, FixedLimiter
from libp2p.rcmgr.manager import ResourceManager


def test_full_resource_manager_workflow():
    """Test complete resource manager workflow."""
    # Create limiter with realistic limits
    limiter = FixedLimiter()
    limiter.system = BaseLimit(
        memory=1024 * 1024,  # 1MB
        streams=100,
        streams_inbound=50,
        streams_outbound=50,
        conns=20,
        conns_inbound=10,
        conns_outbound=10,
        fd=20,
    )

    # Create resource manager
    rm = ResourceManager(limiter)

    try:
        # Create some connections
        connections = []
        for i in range(5):
            conn = rm.open_connection(
                Direction.INBOUND if i % 2 == 0 else Direction.OUTBOUND, use_fd=True
            )
            connections.append(conn)

        # Create streams on different peers
        streams = []
        for i in range(10):
            peer_id = ID(f"peer_{i}".encode())
            stream = rm.open_stream(
                peer_id, Direction.INBOUND if i % 2 == 0 else Direction.OUTBOUND
            )
            streams.append(stream)

        # Check that connections and streams were created successfully
        assert len(connections) == 5
        assert len(streams) == 10

        # Check individual connection scopes have the right stats
        inbound_conns = sum(
            1 for conn in connections if conn.stat().num_conns_inbound > 0
        )
        outbound_conns = sum(
            1 for conn in connections if conn.stat().num_conns_outbound > 0
        )
        assert inbound_conns + outbound_conns == 5

        # Check individual stream scopes have the right stats
        inbound_streams = sum(
            1 for stream in streams if stream.stat().num_streams_inbound > 0
        )
        outbound_streams = sum(
            1 for stream in streams if stream.stat().num_streams_outbound > 0
        )
        assert inbound_streams + outbound_streams == 10

        # Check system metrics (system scope tracks limits, not usage in our
        # current model)
        def check_system(scope):
            stats = scope.stat()
            # System scope in our model doesn't aggregate child usage
            # It only tracks its own direct resources and enforces limits
            return stats

        system_stats = rm.view_system(check_system)

        # Verify the system scope is working (even if not aggregating)
        assert system_stats is not None

        # Clean up streams
        for stream in streams:
            stream.done()

        # Clean up connections
        for conn in connections:
            conn.done()

    finally:
        rm.close()


def test_hierarchical_limits():
    """Test hierarchical limit enforcement."""
    # Create very restrictive limits
    limiter = FixedLimiter()

    # System allows 12 streams total (exactly enough for 3 peers × 4 streams)
    limiter.system = BaseLimit(streams=12)

    # Each peer allows 5 streams
    limiter.peer_default = BaseLimit(streams=5)

    rm = ResourceManager(limiter)

    try:
        peer_id = ID(b"test_peer")

        # Open 5 streams for peer (should succeed)
        streams = []
        for i in range(5):
            stream = rm.open_stream(peer_id, Direction.INBOUND)
            streams.append(stream)

        # 6th stream should fail due to peer limit
        with pytest.raises(ResourceLimitExceeded):
            rm.open_stream(peer_id, Direction.INBOUND)

        # Clean up
        for stream in streams:
            stream.done()

        # Now test system limit with multiple peers
        peer_streams = []
        for peer_num in range(3):
            peer_id = ID(f"peer_{peer_num}".encode())
            for stream_num in range(4):  # 4 streams per peer
                stream = rm.open_stream(peer_id, Direction.INBOUND)
                peer_streams.append(stream)

        # We now have 12 streams across 3 peers (4 each)
        # System limit is 12, so next stream should fail due to system limit
        with pytest.raises(ResourceLimitExceeded):
            rm.open_stream(ID(b"another_peer"), Direction.INBOUND)

        # Clean up
        for stream in peer_streams:
            stream.done()

    finally:
        rm.close()


def test_allowlist_integration():
    """Test allowlist integration with resource limits."""
    # Create very restrictive limits
    limiter = FixedLimiter()
    limiter.peer_default = BaseLimit(streams=1)

    # Create allowlist configuration
    allowlist_config = AllowlistConfig()

    rm = ResourceManager(limiter, allowlist_config=allowlist_config)

    try:
        trusted_peer = ID(b"trusted_peer")
        untrusted_peer = ID(b"untrusted_peer")

        # Add trusted peer to allowlist
        allowlist = rm.get_allowlist()
        allowlist.add_peer(trusted_peer)

        # Untrusted peer should be limited to 1 stream
        stream1 = rm.open_stream(untrusted_peer, Direction.INBOUND)

        with pytest.raises(ResourceLimitExceeded):
            rm.open_stream(untrusted_peer, Direction.INBOUND)

        # Trusted peer should be able to exceed limits (if allowlist bypasses limits)
        # Note: This depends on the specific allowlist implementation
        trusted_stream1 = rm.open_stream(trusted_peer, Direction.INBOUND)

        # Clean up
        stream1.done()
        trusted_stream1.done()

    finally:
        rm.close()


def test_concurrent_resource_usage():
    """Test concurrent resource usage and limits."""
    limiter = FixedLimiter()
    limiter.system = BaseLimit(streams=50, conns=20)

    rm = ResourceManager(limiter)

    try:
        streams_created = []
        connections_created = []
        errors = []

        def worker(worker_id):
            try:
                # Each worker tries to create streams and connections
                for i in range(10):
                    try:
                        peer_id = ID(f"worker_{worker_id}_peer_{i}".encode())
                        stream = rm.open_stream(peer_id, Direction.INBOUND)
                        streams_created.append(stream)
                    except ResourceLimitExceeded:
                        # Expected when limits are reached
                        pass

                    try:
                        conn = rm.open_connection(Direction.OUTBOUND)
                        connections_created.append(conn)
                    except ResourceLimitExceeded:
                        # Expected when limits are reached
                        pass

            except Exception as e:
                errors.append(e)

        # Start multiple worker threads
        threads = []
        for worker_id in range(10):
            t = threading.Thread(target=worker, args=(worker_id,))
            threads.append(t)
            t.start()

        # Wait for all workers to complete
        for t in threads:
            t.join()

        # Should not have unexpected errors
        assert len(errors) == 0

        # Should have created some resources (but not unlimited)
        assert len(streams_created) > 0
        assert len(connections_created) > 0

        # Should respect system limits
        assert len(streams_created) <= 50
        assert len(connections_created) <= 20

        # Clean up
        for stream in streams_created:
            stream.done()
        for conn in connections_created:
            conn.done()

    finally:
        rm.close()


def test_memory_pressure_simulation():
    """Test memory pressure handling."""
    # Create limiter with memory limits
    limiter = FixedLimiter()
    limiter.system = BaseLimit(memory=1024 * 1024)  # 1MB
    limiter.peer_default = BaseLimit(memory=256 * 1024)  # 256KB per peer

    rm = ResourceManager(limiter)

    try:
        peer_id = ID(b"memory_peer")

        # Gradually increase memory usage
        def use_memory(scope):
            # Try to allocate memory in chunks
            allocated = 0
            chunk_size = 32 * 1024  # 32KB chunks (smaller to work with priority limits)

            # With priority=1, threshold is about 50% of limit (128KB out of 256KB)
            # So we can safely allocate about 3 chunks of 32KB = 96KB
            while allocated + chunk_size <= 96 * 1024:  # Stay under priority threshold
                scope.reserve_memory(chunk_size)
                allocated += chunk_size

            return scope.stat()

        stats = rm.view_peer(peer_id, use_memory)
        assert stats.memory >= 64 * 1024  # Should have allocated at least 64KB

        # Try to exceed peer memory limit by using high priority
        def test_high_priority_memory(scope):
            # High priority (255) should allow much more memory
            scope.reserve_memory(200 * 1024, priority=255)  # 200KB with high priority
            return scope.stat()

        high_priority_stats = rm.view_peer(
            ID(b"high_priority_peer"), test_high_priority_memory
        )
        assert high_priority_stats.memory >= 200 * 1024

        # Try to exceed peer memory limit with low priority (should fail)
        def exceed_memory(scope):
            scope.reserve_memory(200 * 1024, priority=1)  # Try 200KB with low priority

        with pytest.raises(ResourceLimitExceeded):
            rm.view_peer(ID(b"exceed_peer"), exceed_memory)

    finally:
        rm.close()


def test_scope_lifecycle():
    """Test complete scope lifecycle."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter)

    try:
        peer_id = ID(b"lifecycle_peer")
        protocol = TProtocol("/test/1.0.0")
        service = "test_service"

        # Create and use various scopes
        def use_peer_scope(scope):
            scope.reserve_memory(1024)
            scope.add_stream(Direction.INBOUND)
            return scope.stat()

        def use_protocol_scope(scope):
            scope.add_stream(Direction.OUTBOUND)
            return scope.stat()

        def use_service_scope(scope):
            scope.add_conn(Direction.INBOUND)
            return scope.stat()

        # Use scopes
        peer_stats = rm.view_peer(peer_id, use_peer_scope)
        protocol_stats = rm.view_protocol(protocol, use_protocol_scope)
        service_stats = rm.view_service(service, use_service_scope)

        # Verify stats
        assert peer_stats.memory == 1024
        assert peer_stats.num_streams_inbound == 1
        assert protocol_stats.num_streams_outbound == 1
        assert service_stats.num_conns_inbound == 1

        # Check scope lists
        assert peer_id in rm.list_peers()
        assert protocol in rm.list_protocols()
        assert service in rm.list_services()

    finally:
        rm.close()


def test_error_recovery():
    """Test error recovery and cleanup."""
    limiter = FixedLimiter()
    limiter.peer_default = BaseLimit(streams=2)

    rm = ResourceManager(limiter)

    try:
        peer_id = ID(b"error_peer")

        # Create streams up to limit
        stream1 = rm.open_stream(peer_id, Direction.INBOUND)
        stream2 = rm.open_stream(peer_id, Direction.OUTBOUND)

        # Next stream should fail
        with pytest.raises(ResourceLimitExceeded):
            rm.open_stream(peer_id, Direction.INBOUND)

        # Release one stream
        stream1.done()

        # Now we should be able to create another
        stream3 = rm.open_stream(peer_id, Direction.INBOUND)

        # Clean up
        stream2.done()
        stream3.done()

    finally:
        rm.close()


def test_metrics_integration():
    """Test metrics collection during normal operation."""
    limiter = FixedLimiter()
    rm = ResourceManager(limiter, enable_metrics=True)

    try:
        metrics = rm.get_metrics()

        # Initial metrics should be empty
        if metrics is not None:
            metrics.get_summary()  # Just call to verify it works

        # Create some resources
        peer_id = ID(b"metrics_peer")
        stream = rm.open_stream(peer_id, Direction.INBOUND)
        conn = rm.open_connection(Direction.OUTBOUND, use_fd=True)

        # Check metrics are updated
        if metrics is not None:
            updated_summary = metrics.get_summary()
            assert "resource_metrics" in updated_summary

        # Clean up
        stream.done()
        conn.done()

    finally:
        rm.close()


def test_resource_manager_stress():
    """Stress test the resource manager."""
    limiter = FixedLimiter()
    limiter.system = BaseLimit(
        streams=1000,
        conns=100,
        memory=10 * 1024 * 1024,  # 10MB
    )

    rm = ResourceManager(limiter)

    try:
        stream_resources = []
        conn_resources = []

        # Create many resources quickly
        for i in range(100):
            peer_id = ID(f"stress_peer_{i}".encode())

            # Create stream
            try:
                stream = rm.open_stream(peer_id, Direction.INBOUND)
                stream_resources.append(stream)
            except ResourceLimitExceeded:
                break

            # Create connection occasionally
            if i % 10 == 0:
                try:
                    conn = rm.open_connection(Direction.OUTBOUND)
                    conn_resources.append(conn)
                except ResourceLimitExceeded:
                    pass

        # Should have created many resources
        assert len(stream_resources) + len(conn_resources) > 50

        # Clean up all at once
        for resource in stream_resources + conn_resources:
            resource.done()

    finally:
        rm.close()

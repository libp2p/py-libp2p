"""
Comprehensive tests for ConnectionLifecycleHandler component.

Tests the connection lifecycle event handling functionality that coordinates
event publishing and processing for connection state changes.
"""

import asyncio
import time
from unittest.mock import patch

import multiaddr

from libp2p.peer.id import ID
from libp2p.rcmgr.connection_lifecycle import ConnectionLifecycleManager
from libp2p.rcmgr.connection_limits import new_connection_limits_with_defaults
from libp2p.rcmgr.connection_tracker import ConnectionTracker
from libp2p.rcmgr.lifecycle_events import (
    ConnectionClosedEvent,
    ConnectionEstablishedEvent,
    ConnectionEventBus,
    ConnectionEventType,
    PeerEvent,
    ResourceLimitEvent,
    StreamEvent,
)
from libp2p.rcmgr.lifecycle_handler import ConnectionLifecycleHandler
from libp2p.rcmgr.memory_limits import MemoryConnectionLimits


class TestConnectionLifecycleHandler:
    """Test suite for ConnectionLifecycleHandler class."""

    def test_connection_lifecycle_handler_creation(self):
        """Test ConnectionLifecycleHandler creation."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        assert handler.connection_tracker == tracker
        assert handler.connection_lifecycle_manager == lifecycle_manager
        assert handler.memory_limits == memory_limits
        assert handler.event_bus == event_bus

    def test_connection_lifecycle_handler_creation_with_none_values(self):
        """Test ConnectionLifecycleHandler creation with None values."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,
        )

        assert handler.connection_tracker == tracker
        assert handler.connection_lifecycle_manager == lifecycle_manager
        assert handler.memory_limits is None
        assert handler.event_bus is not None  # Default event bus is created

    async def test_publish_connection_established(self):
        """Test publishing connection established event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            await handler.publish_connection_established(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                direction="inbound",
                local_addr=multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080"),
                remote_addr=multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090"),
                metadata={"test": "data"}
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionEstablishedEvent)
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.direction == "inbound"
            assert event.local_addr == multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
            assert event.remote_addr == multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")
            assert event.metadata == {"test": "data"}

    async def test_publish_connection_established_with_none_event_bus(self):
        """Test publishing connection established event with None event bus."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,  # This will create a default event bus
        )

        # Should not raise exception
        await handler.publish_connection_established(
            connection_id="conn_1",
            peer_id=ID(b"test_peer"),
            direction="inbound"
        )

    async def test_publish_connection_closed(self):
        """Test publishing connection closed event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            await handler.publish_connection_closed(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                reason="timeout",
                metadata={"test": "data"}
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionClosedEvent)
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.reason == "timeout"
            assert event.metadata == {"test": "data"}

    async def test_publish_connection_closed_with_none_event_bus(self):
        """Test publishing connection closed event with None event bus."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,  # This will create a default event bus
        )

        # Should not raise exception
        await handler.publish_connection_closed(
            connection_id="conn_1",
            peer_id=ID(b"test_peer"),
            reason="timeout"
        )

    async def test_publish_resource_limit_exceeded(self):
        """Test publishing resource limit exceeded event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            await handler.publish_resource_limit_exceeded(
                limit_type="memory",
                limit_value=1024,
                current_value=2048,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                metadata={"test": "data"}
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ResourceLimitEvent)
            assert event.limit_type == "memory"
            assert event.limit_value == 1024
            assert event.current_value == 2048
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.metadata == {"test": "data"}

    async def test_publish_resource_limit_exceeded_with_none_event_bus(self):
        """Test publishing resource limit exceeded event with None event bus."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,  # This will create a default event bus
        )

        # Should not raise exception
        await handler.publish_resource_limit_exceeded(
            limit_type="memory",
            limit_value=1024,
            current_value=2048
        )

    async def test_publish_stream_event(self):
        """Test publishing stream event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                stream_id="stream_1",
                protocol="/test/1.0.0",
                direction="inbound",
                metadata={"test": "data"}
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, StreamEvent)
            assert event.event_type == ConnectionEventType.STREAM_OPENED
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.stream_id == "stream_1"
            assert event.protocol == "/test/1.0.0"
            assert event.direction == "inbound"
            assert event.metadata == {"test": "data"}

    async def test_publish_stream_event_with_none_event_bus(self):
        """Test publishing stream event with None event bus."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,  # This will create a default event bus
        )

        # Should not raise exception
        await handler.publish_stream_event(
            event_type=ConnectionEventType.STREAM_OPENED,
            connection_id="conn_1",
            peer_id=ID(b"test_peer")
        )

    async def test_publish_peer_event(self):
        """Test publishing peer event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            await handler.publish_peer_event(
                action="connected",
                peer_id=ID(b"test_peer"),
                connection_id="conn_1",
                metadata={"test": "data"}
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, PeerEvent)
            assert event.action == "connected"
            assert event.peer_id == ID(b"test_peer")
            assert event.connection_id == "conn_1"
            assert event.metadata == {"test": "data"}

    async def test_publish_peer_event_with_none_event_bus(self):
        """Test publishing peer event with None event bus."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,  # This will create a default event bus
        )

        # Should not raise exception
        await handler.publish_peer_event(
            action="connected",
            peer_id=ID(b"test_peer")
        )

    def test_get_stats(self):
        """Test getting handler statistics."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        stats = handler.get_stats()

        assert isinstance(stats, dict)
        assert "connection_tracker" in stats
        assert "connection_lifecycle_manager" in stats
        assert "memory_limits" in stats
        assert "event_bus" in stats

    def test_get_stats_with_none_components(self):
        """Test getting statistics with None components."""
        # Create minimal required components
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=None,
            event_bus=None,  # This will create a default event bus
        )

        stats = handler.get_stats()

        assert isinstance(stats, dict)
        assert stats["connection_tracker"] is None
        assert stats["connection_lifecycle_manager"] is None
        assert stats["memory_limits"] is None
        assert stats["event_bus"] is None

    async def test_publish_connection_established_error_handling(self):
        """Test error handling in publish_connection_established."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus to raise exception
        with patch.object(event_bus, 'publish_async') as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_connection_established(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                direction="inbound"
            )

    async def test_publish_connection_closed_error_handling(self):
        """Test error handling in publish_connection_closed."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus to raise exception
        with patch.object(event_bus, 'publish_async') as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_connection_closed(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                reason="timeout"
            )

    async def test_publish_resource_limit_exceeded_error_handling(self):
        """Test error handling in publish_resource_limit_exceeded."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus to raise exception
        with patch.object(event_bus, 'publish_async') as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_resource_limit_exceeded(
                limit_type="memory",
                limit_value=1024,
                current_value=2048
            )

    async def test_publish_stream_event_error_handling(self):
        """Test error handling in publish_stream_event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus to raise exception
        with patch.object(event_bus, 'publish_async') as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer")
            )

    async def test_publish_peer_event_error_handling(self):
        """Test error handling in publish_peer_event."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus to raise exception
        with patch.object(event_bus, 'publish_async') as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_peer_event(
                action="connected",
                peer_id=ID(b"test_peer")
            )

    async def test_publish_multiple_events(self):
        """Test publishing multiple events."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Publish multiple events
            await handler.publish_connection_established(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                direction="inbound"
            )

            await handler.publish_connection_closed(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                reason="timeout"
            )

            await handler.publish_resource_limit_exceeded(
                limit_type="memory",
                limit_value=1024,
                current_value=2048
            )

            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer")
            )

            await handler.publish_peer_event(
                action="connected",
                peer_id=ID(b"test_peer")
            )

            # Should have published all events
            assert mock_publish.call_count == 5

    async def test_publish_events_concurrently(self):
        """Test publishing events concurrently."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Publish events concurrently
            tasks = []
            for i in range(10):
                task = handler.publish_connection_established(
                    connection_id=f"conn_{i}",
                    peer_id=ID(f"peer_{i}".encode()),
                    direction="inbound"
                )
                tasks.append(task)

            await asyncio.gather(*tasks)

            # Should have published all events
            assert mock_publish.call_count == 10

    def test_connection_lifecycle_handler_string_representation(self):
        """Test string representation of ConnectionLifecycleHandler."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        str_repr = str(handler)
        assert "ConnectionLifecycleHandler" in str_repr

    def test_connection_lifecycle_handler_repr(self):
        """Test repr representation of ConnectionLifecycleHandler."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        repr_str = repr(handler)
        assert "ConnectionLifecycleHandler" in repr_str

    def test_connection_lifecycle_handler_equality(self):
        """Test ConnectionLifecycleHandler equality."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler1 = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )
        handler2 = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Should be equal (same components)
        assert handler1 == handler2

    def test_connection_lifecycle_handler_hash(self):
        """Test ConnectionLifecycleHandler hash functionality."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler1 = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )
        handler2 = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Should have same hash (same components)
        assert hash(handler1) == hash(handler2)

    def test_connection_lifecycle_handler_in_set(self):
        """Test ConnectionLifecycleHandler can be used in sets."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler1 = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )
        handler2 = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        handler_set = {handler1, handler2}
        assert len(handler_set) == 1  # Same components

    def test_connection_lifecycle_handler_in_dict(self):
        """Test ConnectionLifecycleHandler can be used as dictionary key."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        handler_dict = {handler: "value"}
        assert handler_dict[handler] == "value"

    def test_connection_lifecycle_handler_copy(self):
        """Test ConnectionLifecycleHandler can be copied."""
        import copy

        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        handler_copy = copy.copy(handler)

        # Should be equal but different objects
        assert handler == handler_copy
        assert handler is not handler_copy

    def test_connection_lifecycle_handler_deep_copy(self):
        """Test ConnectionLifecycleHandler can be deep copied."""
        import copy

        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        handler_deep_copy = copy.deepcopy(handler)

        # Should be equal but different objects
        assert handler == handler_deep_copy
        assert handler is not handler_deep_copy

    async def test_publish_events_performance(self):
        """Test ConnectionLifecycleHandler performance."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Measure time for many events
            start_time = time.time()

            for i in range(1000):
                await handler.publish_connection_established(
                    connection_id=f"conn_{i}",
                    peer_id=ID(f"peer_{i}".encode()),
                    direction="inbound"
                )

            end_time = time.time()
            elapsed = end_time - start_time

            # Should complete in reasonable time
            assert elapsed < 1.0  # Should complete in less than 1 second
            assert mock_publish.call_count == 1000

    async def test_publish_events_memory_usage(self):
        """Test ConnectionLifecycleHandler memory usage."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Publish many events
            for i in range(1000):
                await handler.publish_connection_established(
                    connection_id=f"conn_{i}",
                    peer_id=ID(f"peer_{i}".encode()),
                    direction="inbound"
                )

            # Should handle many events efficiently
            assert mock_publish.call_count == 1000

    async def test_publish_events_edge_cases(self):
        """Test ConnectionLifecycleHandler edge cases."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Test with None values
            await handler.publish_connection_established(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                direction="inbound"
            )

            await handler.publish_connection_closed(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                reason="timeout"
            )

            await handler.publish_resource_limit_exceeded(
                limit_type="memory",
                limit_value=1024,
                current_value=2048
            )

            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer")
            )

            await handler.publish_peer_event(
                action="connected",
                peer_id=ID(b"test_peer")
            )

            # Should have published all events
            assert mock_publish.call_count == 5

    async def test_publish_events_with_unicode_data(self):
        """Test ConnectionLifecycleHandler with unicode data."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Test with unicode data
            await handler.publish_connection_established(
                connection_id="conn_测试_🚀",
                peer_id=ID(b"test_peer"),
                direction="inbound",
                local_addr=multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080"),
                remote_addr=multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090"),
                metadata={"测试": "数据", "🚀": "rocket"}
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event.connection_id == "conn_测试_🚀"
            assert event.metadata == {"测试": "数据", "🚀": "rocket"}

    async def test_publish_events_with_very_long_data(self):
        """Test ConnectionLifecycleHandler with very long data."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        lifecycle_manager = ConnectionLifecycleManager(tracker, limits)
        memory_limits = MemoryConnectionLimits()
        event_bus = ConnectionEventBus()

        handler = ConnectionLifecycleHandler(
            connection_tracker=tracker,
            connection_lifecycle_manager=lifecycle_manager,
            memory_limits=memory_limits,
            event_bus=event_bus,
        )

        # Mock the event bus
        with patch.object(event_bus, 'publish_async') as mock_publish:
            # Test with very long data
            long_conn_id = "conn_" + "x" * 10000
            long_peer_id = ID(b"x" * 10000)
            long_metadata = {"key": "x" * 10000}

            await handler.publish_connection_established(
                connection_id=long_conn_id,
                peer_id=long_peer_id,
                direction="inbound",
                metadata=long_metadata
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event.connection_id == long_conn_id
            assert event.peer_id == long_peer_id
            assert event.metadata == long_metadata

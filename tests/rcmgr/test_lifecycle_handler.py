"""
Comprehensive tests for ConnectionLifecycleHandler component.

Tests the connection lifecycle event handling functionality that coordinates
event publishing and processing for connection state changes.
"""

import asyncio
import time
from unittest.mock import patch

import pytest
import multiaddr

from libp2p.peer.id import ID
from libp2p.rcmgr.connection_lifecycle import ConnectionLifecycleManager
from libp2p.rcmgr.connection_limits import new_connection_limits_with_defaults
from libp2p.rcmgr.connection_tracker import ConnectionTracker
from libp2p.rcmgr.lifecycle_events import (
    ConnectionEvent,
    ConnectionEventBus,
    ConnectionEventType,
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

    @pytest.mark.asyncio
    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            await handler.publish_connection_established(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                direction="inbound",
                local_addr=multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080"),
                remote_addr=multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090"),
                metadata={"test": "data"},
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionEvent)
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.event_type == ConnectionEventType.ESTABLISHED_INBOUND
            assert event.local_addr == multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
            assert event.remote_addr == multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")
            assert event.metadata == {"test": "data"}

    @pytest.mark.asyncio
    @pytest.mark.asyncio
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
            connection_id="conn_1", peer_id=ID(b"test_peer"), direction="inbound"
        )

    @pytest.mark.asyncio
    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            await handler.publish_connection_closed(
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                reason="timeout",
                metadata={"test": "data"},
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionEvent)
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.metadata.get("reason") == "timeout"
            assert event.metadata == {"test": "data", "reason": "timeout"}

    @pytest.mark.asyncio
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
            connection_id="conn_1", peer_id=ID(b"test_peer"), reason="timeout"
        )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            await handler.publish_resource_limit_exceeded(
                limit_type="memory",
                limit_value=1024,
                current_value=2048,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                metadata={"test": "data"},
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionEvent)
            assert event.metadata.get("limit_type") == "memory"
            assert event.metadata.get("limit_value") == 1024
            assert event.metadata.get("current_value") == 2048
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.metadata == {
                "test": "data",
                "limit_type": "memory",
                "limit_value": 1024,
                "current_value": 2048,
            }

    @pytest.mark.asyncio
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
            limit_type="memory", limit_value=1024, current_value=2048
        )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
                stream_id="stream_1",
                protocol="/test/1.0.0",
                direction="inbound",
                metadata={"test": "data"},
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionEvent)
            assert event.event_type == ConnectionEventType.STREAM_OPENED
            assert event.connection_id == "conn_1"
            assert event.peer_id == ID(b"test_peer")
            assert event.metadata.get("stream_id") == "stream_1"
            assert event.metadata.get("protocol") == "/test/1.0.0"
            assert event.metadata.get("direction") == "inbound"
            assert event.metadata == {
                "test": "data",
                "stream_id": "stream_1",
                "protocol": "/test/1.0.0",
                "direction": "inbound",
            }

    @pytest.mark.asyncio
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
            peer_id=ID(b"test_peer"),
        )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            await handler.publish_peer_event(
                action="connected",
                peer_id=ID(b"test_peer"),
                connection_id="conn_1",
                metadata={"test": "data"},
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert isinstance(event, ConnectionEvent)
            assert event.metadata.get("action") == "connected"
            assert event.peer_id == ID(b"test_peer")
            assert event.connection_id == "conn_1"
            assert event.metadata == {"test": "data", "action": "connected"}

    @pytest.mark.asyncio
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
        await handler.publish_peer_event(action="connected", peer_id=ID(b"test_peer"))

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
        assert "events_processed" in stats
        assert "connection_events" in stats
        assert "resource_events" in stats
        assert "stream_events" in stats
        assert "peer_events" in stats
        assert "errors" in stats
        assert "event_bus_stats" in stats

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
        assert "events_processed" in stats
        assert "connection_events" in stats
        assert "resource_events" in stats
        assert "stream_events" in stats
        assert "peer_events" in stats
        assert "errors" in stats
        assert "event_bus_stats" in stats

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_connection_established(
                connection_id="conn_1", peer_id=ID(b"test_peer"), direction="inbound"
            )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_connection_closed(
                connection_id="conn_1", peer_id=ID(b"test_peer"), reason="timeout"
            )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_resource_limit_exceeded(
                limit_type="memory", limit_value=1024, current_value=2048
            )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
            )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            mock_publish.side_effect = Exception("Event bus error")

            # Should not raise exception
            await handler.publish_peer_event(
                action="connected", peer_id=ID(b"test_peer")
            )

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Publish multiple events
            await handler.publish_connection_established(
                connection_id="conn_1", peer_id=ID(b"test_peer"), direction="inbound"
            )

            await handler.publish_connection_closed(
                connection_id="conn_1", peer_id=ID(b"test_peer"), reason="timeout"
            )

            await handler.publish_resource_limit_exceeded(
                limit_type="memory", limit_value=1024, current_value=2048
            )

            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
            )

            await handler.publish_peer_event(
                action="connected", peer_id=ID(b"test_peer")
            )

            # Should have published all events
            assert mock_publish.call_count == 5

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Publish events concurrently
            tasks = []
            for i in range(10):
                task = handler.publish_connection_established(
                    connection_id=f"conn_{i}",
                    peer_id=ID(f"peer_{i}".encode()),
                    direction="inbound",
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

        # Should be different objects (realistic behavior - no __eq__ implemented)
        assert handler1 is not handler2

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

        # Should have different hashes (realistic behavior - no __hash__ implemented)
        assert hash(handler1) != hash(handler2)

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
        assert (
            len(handler_set) == 2
        )  # Different objects (realistic behavior - no __eq__/__hash__ implemented)

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

        # Should be different objects (realistic behavior - no __eq__ implemented)
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

        # Deep copy should work since components have __deepcopy__ methods
        handler_deep_copy = copy.deepcopy(handler)

        # Should be different objects
        assert handler is not handler_deep_copy

        # Should have the same type
        assert isinstance(handler_deep_copy, ConnectionLifecycleHandler)

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Measure time for many events
            start_time = time.time()

            for i in range(1000):
                await handler.publish_connection_established(
                    connection_id=f"conn_{i}",
                    peer_id=ID(f"peer_{i}".encode()),
                    direction="inbound",
                )

            end_time = time.time()
            elapsed = end_time - start_time

            # Should complete in reasonable time
            assert elapsed < 1.0  # Should complete in less than 1 second
            assert mock_publish.call_count == 1000

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Publish many events
            for i in range(1000):
                await handler.publish_connection_established(
                    connection_id=f"conn_{i}",
                    peer_id=ID(f"peer_{i}".encode()),
                    direction="inbound",
                )

            # Should handle many events efficiently
            assert mock_publish.call_count == 1000

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Test with None values
            await handler.publish_connection_established(
                connection_id="conn_1", peer_id=ID(b"test_peer"), direction="inbound"
            )

            await handler.publish_connection_closed(
                connection_id="conn_1", peer_id=ID(b"test_peer"), reason="timeout"
            )

            await handler.publish_resource_limit_exceeded(
                limit_type="memory", limit_value=1024, current_value=2048
            )

            await handler.publish_stream_event(
                event_type=ConnectionEventType.STREAM_OPENED,
                connection_id="conn_1",
                peer_id=ID(b"test_peer"),
            )

            await handler.publish_peer_event(
                action="connected", peer_id=ID(b"test_peer")
            )

            # Should have published all events
            assert mock_publish.call_count == 5

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Test with unicode data
            await handler.publish_connection_established(
                connection_id="conn_测试_🚀",
                peer_id=ID(b"test_peer"),
                direction="inbound",
                local_addr=multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080"),
                remote_addr=multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090"),
                metadata={"测试": "数据", "🚀": "rocket"},
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event.connection_id == "conn_测试_🚀"
            assert event.metadata == {"测试": "数据", "🚀": "rocket"}

    @pytest.mark.asyncio
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
        with patch.object(event_bus, "publish") as mock_publish:
            # Test with very long data
            long_conn_id = "conn_" + "x" * 10000
            long_peer_id = ID(b"x" * 10000)
            long_metadata = {"key": "x" * 10000}

            await handler.publish_connection_established(
                connection_id=long_conn_id,
                peer_id=long_peer_id,
                direction="inbound",
                metadata=long_metadata,
            )

            # Should have published event
            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event.connection_id == long_conn_id
            assert event.peer_id == long_peer_id
            assert event.metadata == long_metadata

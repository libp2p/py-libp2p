"""
Connection lifecycle events for resource management.

This module implements connection lifecycle events that provide hooks for
connection state changes and integrate with the resource management system.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Protocol, runtime_checkable

import multiaddr

from libp2p.peer.id import ID

logger = logging.getLogger(__name__)


class ConnectionEventType(Enum):
    """Types of connection lifecycle events."""

    # Connection establishment events
    PENDING_INBOUND = "pending_inbound"
    PENDING_OUTBOUND = "pending_outbound"
    ESTABLISHED_INBOUND = "established_inbound"
    ESTABLISHED_OUTBOUND = "established_outbound"

    # Connection state change events
    CONNECTION_OPENED = "connection_opened"
    CONNECTION_CLOSED = "connection_closed"
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_RESET = "connection_reset"

    # Resource management events
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    RESOURCE_LIMIT_RECOVERED = "resource_limit_recovered"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    MEMORY_LIMIT_RECOVERED = "memory_limit_recovered"

    # Stream lifecycle events
    STREAM_OPENED = "stream_opened"
    STREAM_CLOSED = "stream_closed"
    STREAM_FAILED = "stream_failed"

    # Peer events
    PEER_CONNECTED = "peer_connected"
    PEER_DISCONNECTED = "peer_disconnected"
    PEER_BYPASSED = "peer_bypassed"
    PEER_UNBYPASSED = "peer_unbypassed"


@dataclass
class ConnectionEvent:
    """Base class for connection lifecycle events."""

    event_type: ConnectionEventType
    timestamp: float = field(default_factory=time.time)
    connection_id: str | None = None
    peer_id: ID | None = None
    local_addr: multiaddr.Multiaddr | None = None
    remote_addr: multiaddr.Multiaddr | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """String representation of the event."""
        return (
            f"{self.event_type.value}("
            f"connection_id={self.connection_id}, "
            f"peer_id={self.peer_id}, "
            f"timestamp={self.timestamp})"
        )


@dataclass
class ConnectionEstablishedEvent(ConnectionEvent):
    """Event fired when a connection is established."""

    event_type: ConnectionEventType = ConnectionEventType.ESTABLISHED_INBOUND
    direction: str = "inbound"  # "inbound" or "outbound"
    endpoint: str | None = None

    def __post_init__(self) -> None:
        """Set event type based on direction."""
        if self.direction == "inbound":
            self.event_type = ConnectionEventType.ESTABLISHED_INBOUND
        else:
            self.event_type = ConnectionEventType.ESTABLISHED_OUTBOUND


@dataclass
class ConnectionClosedEvent(ConnectionEvent):
    """Event fired when a connection is closed."""

    event_type: ConnectionEventType = ConnectionEventType.CONNECTION_CLOSED
    reason: str = "unknown"
    duration: float | None = None


@dataclass
class ResourceLimitEvent(ConnectionEvent):
    """Event fired when resource limits are exceeded or recovered."""

    event_type: ConnectionEventType = ConnectionEventType.RESOURCE_LIMIT_EXCEEDED
    limit_type: str = "connection"  # "connection", "memory", "stream", etc.
    limit_value: int | float = 0
    current_value: int | float = 0
    recovered: bool = False

    def __post_init__(self) -> None:
        """Set event type based on limit type and recovery status."""
        if self.limit_type == "memory":
            if self.recovered:
                self.event_type = ConnectionEventType.MEMORY_LIMIT_RECOVERED
            else:
                self.event_type = ConnectionEventType.MEMORY_LIMIT_EXCEEDED
        else:
            if self.recovered:
                self.event_type = ConnectionEventType.RESOURCE_LIMIT_RECOVERED
            else:
                self.event_type = ConnectionEventType.RESOURCE_LIMIT_EXCEEDED


@dataclass
class StreamEvent(ConnectionEvent):
    """Event fired for stream lifecycle changes."""

    event_type: ConnectionEventType = ConnectionEventType.STREAM_OPENED
    stream_id: str | None = None
    protocol: str | None = None
    direction: str | None = None  # "inbound" or "outbound"


@dataclass
class PeerEvent(ConnectionEvent):
    """Event fired for peer-related changes."""

    event_type: ConnectionEventType = ConnectionEventType.PEER_CONNECTED
    action: str = "connected"  # "connected", "disconnected", "bypassed", "unbypassed"

    def __post_init__(self) -> None:
        """Set event type based on action."""
        if self.action == "connected":
            self.event_type = ConnectionEventType.PEER_CONNECTED
        elif self.action == "disconnected":
            self.event_type = ConnectionEventType.PEER_DISCONNECTED
        elif self.action == "bypassed":
            self.event_type = ConnectionEventType.PEER_BYPASSED
        elif self.action == "unbypassed":
            self.event_type = ConnectionEventType.PEER_UNBYPASSED


@runtime_checkable
class ConnectionEventHandler(Protocol):
    """Protocol for connection event handlers."""

    async def handle_event(self, event: ConnectionEvent) -> None:
        """
        Handle a connection lifecycle event.

        Args:
            event: The connection event to handle

        """
        ...


@runtime_checkable
class AsyncConnectionEventHandler(Protocol):
    """Protocol for async connection event handlers."""

    async def handle_event(self, event: ConnectionEvent) -> None:
        """
        Handle a connection lifecycle event asynchronously.

        Args:
            event: The connection event to handle

        """
        ...


class ConnectionEventBus:
    """
    Event bus for connection lifecycle events.

    This class provides a centralized event system for connection lifecycle
    events, allowing components to subscribe to and publish events.
    """

    def __init__(self, max_event_history: int = 1000):
        """
        Initialize connection event bus.

        Args:
            max_event_history: Maximum number of events to keep in history

        """
        self.max_event_history = max_event_history
        self._handlers: dict[ConnectionEventType, list[ConnectionEventHandler]] = {}
        self._async_handlers: dict[
            ConnectionEventType, list[AsyncConnectionEventHandler]
        ] = {}
        self._event_history: list[ConnectionEvent] = []
        self._lock = asyncio.Lock()

        logger.debug(
            f"Initialized ConnectionEventBus with max_history={max_event_history}"
        )

    def subscribe(
        self,
        event_type: ConnectionEventType,
        handler: ConnectionEventHandler | AsyncConnectionEventHandler,
    ) -> None:
        """
        Subscribe to events of a specific type.

        Args:
            event_type: Type of events to subscribe to
            handler: Event handler to call when events occur

        """
        if isinstance(handler, AsyncConnectionEventHandler):
            if event_type not in self._async_handlers:
                self._async_handlers[event_type] = []
            self._async_handlers[event_type].append(handler)
        else:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

        logger.debug(f"Subscribed handler to {event_type.value} events")

    def unsubscribe(
        self,
        event_type: ConnectionEventType,
        handler: ConnectionEventHandler | AsyncConnectionEventHandler,
    ) -> None:
        """
        Unsubscribe from events of a specific type.

        Args:
            event_type: Type of events to unsubscribe from
            handler: Event handler to remove

        """
        if isinstance(handler, AsyncConnectionEventHandler):
            if event_type in self._async_handlers:
                try:
                    self._async_handlers[event_type].remove(handler)
                except ValueError:
                    pass
        else:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass

        logger.debug(f"Unsubscribed handler from {event_type.value} events")

    async def publish(self, event: ConnectionEvent) -> None:
        """
        Publish a connection event.

        Args:
            event: The event to publish

        """
        async with self._lock:
            # Add to event history
            self._event_history.append(event)
            if len(self._event_history) > self.max_event_history:
                self._event_history.pop(0)

            # Notify handlers
            await self._notify_handlers(event)

            logger.debug(f"Published event: {event}")

    async def _notify_handlers(self, event: ConnectionEvent) -> None:
        """
        Notify all handlers for an event type.

        Args:
            event: The event to notify handlers about

        """
        # Notify sync handlers
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                try:
                    await handler.handle_event(event)
                except Exception as e:
                    logger.error(
                        f"Error in sync handler for {event.event_type.value}: {e}"
                    )

        # Notify async handlers
        if event.event_type in self._async_handlers:
            for handler in self._async_handlers[event.event_type]:
                try:
                    await handler.handle_event(event)
                except Exception as e:
                    logger.error(
                        f"Error in async handler for {event.event_type.value}: {e}"
                    )

    def get_event_history(
        self,
        event_type: ConnectionEventType | None = None,
        limit: int | None = None,
    ) -> list[ConnectionEvent]:
        """
        Get event history.

        Args:
            event_type: Filter by event type, or None for all events
            limit: Maximum number of events to return

        Returns:
            List of events

        """
        events = self._event_history

        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]

        if limit is not None:
            events = events[-limit:]

        return events

    def get_event_stats(self) -> dict[str, Any]:
        """
        Get event statistics.

        Returns:
            Dictionary of event statistics

        """
        stats: dict[str, Any] = {}

        # Count events by type
        for event in self._event_history:
            event_type = event.event_type.value
            stats[event_type] = stats.get(event_type, 0) + 1

        # Add summary statistics
        stats["total_events"] = len(self._event_history)
        stats["unique_event_types"] = len({e.event_type for e in self._event_history})
        stats["handler_counts"] = {
            event_type.value: len(handlers)
            for event_type, handlers in self._handlers.items()
        }
        stats["async_handler_counts"] = {
            event_type.value: len(handlers)
            for event_type, handlers in self._async_handlers.items()
        }

        return stats

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()
        logger.debug("Cleared event history")

    def __str__(self) -> str:
        """String representation of event bus."""
        stats = self.get_event_stats()
        return (
            f"ConnectionEventBus("
            f"total_events={stats['total_events']}, "
            f"unique_types={stats['unique_event_types']})"
        )

"""
Connection lifecycle handler for resource management.

This module implements connection lifecycle handlers that integrate with
the resource management system and provide hooks for connection state changes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import multiaddr

from libp2p.peer.id import ID

from .connection_lifecycle import ConnectionLifecycleManager
from .connection_tracker import ConnectionTracker
from .lifecycle_events import (
    AsyncConnectionEventHandler,
    ConnectionClosedEvent,
    ConnectionEstablishedEvent,
    ConnectionEvent,
    ConnectionEventBus,
    ConnectionEventType,
    PeerEvent,
    ResourceLimitEvent,
    StreamEvent,
)
from .memory_limits import MemoryConnectionLimits

logger = logging.getLogger(__name__)


class ConnectionLifecycleHandler(AsyncConnectionEventHandler):
    """
    Handler for connection lifecycle events.

    This class integrates connection lifecycle events with the resource
    management system, providing hooks for connection state changes
    and resource limit monitoring.
    """

    def __init__(
        self,
        connection_tracker: ConnectionTracker,
        connection_lifecycle_manager: ConnectionLifecycleManager,
        memory_limits: MemoryConnectionLimits | None = None,
        event_bus: ConnectionEventBus | None = None,
    ):
        """
        Initialize connection lifecycle handler.

        Args:
            connection_tracker: Connection state tracker
            connection_lifecycle_manager: Connection lifecycle manager
            memory_limits: Memory limits for monitoring
            event_bus: Event bus for publishing events

        """
        self.connection_tracker = connection_tracker
        self.connection_lifecycle_manager = connection_lifecycle_manager
        self.memory_limits = memory_limits
        self.event_bus = event_bus or ConnectionEventBus()

        # Statistics
        self._stats = {
            "events_processed": 0,
            "connection_events": 0,
            "resource_events": 0,
            "stream_events": 0,
            "peer_events": 0,
            "errors": 0,
        }

        logger.debug("Initialized ConnectionLifecycleHandler")

    async def handle_event(self, event: ConnectionEvent) -> None:
        """
        Handle a connection lifecycle event.

        Args:
            event: The connection event to handle

        """
        try:
            self._stats["events_processed"] += 1

            # Route event to appropriate handler
            if event.event_type in [
                ConnectionEventType.ESTABLISHED_INBOUND,
                ConnectionEventType.ESTABLISHED_OUTBOUND,
            ]:
                await self._handle_connection_established(event)
            elif event.event_type == ConnectionEventType.CONNECTION_CLOSED:
                await self._handle_connection_closed(event)
            elif event.event_type in [
                ConnectionEventType.RESOURCE_LIMIT_EXCEEDED,
                ConnectionEventType.MEMORY_LIMIT_EXCEEDED,
            ]:
                await self._handle_resource_limit_exceeded(event)
            elif event.event_type in [
                ConnectionEventType.STREAM_OPENED,
                ConnectionEventType.STREAM_CLOSED,
            ]:
                await self._handle_stream_event(event)
            elif event.event_type in [
                ConnectionEventType.PEER_CONNECTED,
                ConnectionEventType.PEER_DISCONNECTED,
            ]:
                await self._handle_peer_event(event)

            logger.debug(f"Processed event: {event}")

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Error handling event {event}: {e}")

    async def _handle_connection_established(self, event: ConnectionEvent) -> None:
        """Handle connection established events."""
        self._stats["connection_events"] += 1

        # Update connection tracker
        if event.connection_id and event.peer_id:
            if event.event_type == ConnectionEventType.ESTABLISHED_INBOUND:
                self.connection_tracker.move_to_established_inbound(
                    event.connection_id, event.peer_id
                )
            elif event.event_type == ConnectionEventType.ESTABLISHED_OUTBOUND:
                self.connection_tracker.move_to_established_outbound(
                    event.connection_id, event.peer_id
                )

        # Publish established event
        established_event = ConnectionEstablishedEvent(
            event_type=event.event_type,
            timestamp=event.timestamp,
            connection_id=event.connection_id,
            peer_id=event.peer_id,
            local_addr=event.local_addr,
            remote_addr=event.remote_addr,
            direction=(
                "inbound" if event.event_type == ConnectionEventType.ESTABLISHED_INBOUND
                else "outbound"
            ),
            metadata=event.metadata,
        )
        await self.event_bus.publish(established_event)

    async def _handle_connection_closed(self, event: ConnectionEvent) -> None:
        """Handle connection closed events."""
        self._stats["connection_events"] += 1

        # Update connection tracker
        if event.connection_id:
            self.connection_tracker.remove_connection(
                event.connection_id, event.peer_id
            )

        # Publish closed event
        closed_event = ConnectionClosedEvent(
            event_type=ConnectionEventType.CONNECTION_CLOSED,
            connection_id=event.connection_id,
            peer_id=event.peer_id,
            local_addr=event.local_addr,
            remote_addr=event.remote_addr,
            reason=event.metadata.get("reason", "unknown"),
            metadata=event.metadata,
        )
        await self.event_bus.publish(closed_event)

    async def _handle_resource_limit_exceeded(self, event: ConnectionEvent) -> None:
        """Handle resource limit exceeded events."""
        self._stats["resource_events"] += 1

        # Create resource limit event
        limit_event = ResourceLimitEvent(
            event_type=event.event_type,
            timestamp=event.timestamp,
            connection_id=event.connection_id,
            peer_id=event.peer_id,
            limit_type=event.metadata.get("limit_type", "unknown"),
            limit_value=event.metadata.get("limit_value", 0),
            current_value=event.metadata.get("current_value", 0),
            recovered=False,
            metadata=event.metadata,
        )
        await self.event_bus.publish(limit_event)

    async def _handle_stream_event(self, event: ConnectionEvent) -> None:
        """Handle stream lifecycle events."""
        self._stats["stream_events"] += 1

        # Create stream event
        stream_event = StreamEvent(
            event_type=event.event_type,
            connection_id=event.connection_id,
            peer_id=event.peer_id,
            stream_id=event.metadata.get("stream_id"),
            protocol=event.metadata.get("protocol"),
            direction=event.metadata.get("direction"),
            metadata=event.metadata,
        )
        await self.event_bus.publish(stream_event)

    async def _handle_peer_event(self, event: ConnectionEvent) -> None:
        """Handle peer-related events."""
        self._stats["peer_events"] += 1

        # Create peer event
        peer_event = PeerEvent(
            event_type=event.event_type,
            timestamp=event.timestamp,
            connection_id=event.connection_id,
            peer_id=event.peer_id,
            action=event.metadata.get("action", "unknown"),
            metadata=event.metadata,
        )
        await self.event_bus.publish(peer_event)

    async def publish_connection_established(
        self,
        connection_id: str,
        peer_id: ID,
        direction: str,
        local_addr: multiaddr.Multiaddr | None = None,
        remote_addr: multiaddr.Multiaddr | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a connection established event.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID
            direction: Connection direction ("inbound" or "outbound")
            local_addr: Local address
            remote_addr: Remote address
            metadata: Additional event metadata

        """
        event_type = (
            ConnectionEventType.ESTABLISHED_INBOUND
            if direction == "inbound"
            else ConnectionEventType.ESTABLISHED_OUTBOUND
        )

        event = ConnectionEvent(
            event_type=event_type,
            connection_id=connection_id,
            peer_id=peer_id,
            local_addr=local_addr,
            remote_addr=remote_addr,
            metadata=metadata or {},
        )

        await self.event_bus.publish(event)

    async def publish_connection_closed(
        self,
        connection_id: str,
        peer_id: ID | None = None,
        reason: str = "unknown",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a connection closed event.

        Args:
            connection_id: Connection identifier
            peer_id: Peer ID if known
            reason: Reason for connection closure
            metadata: Additional event metadata

        """
        event = ConnectionEvent(
            event_type=ConnectionEventType.CONNECTION_CLOSED,
            connection_id=connection_id,
            peer_id=peer_id,
            metadata={**(metadata or {}), "reason": reason},
        )

        await self.event_bus.publish(event)

    async def publish_resource_limit_exceeded(
        self,
        limit_type: str,
        limit_value: int | float,
        current_value: int | float,
        connection_id: str | None = None,
        peer_id: ID | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a resource limit exceeded event.

        Args:
            limit_type: Type of limit exceeded
            limit_value: Limit value
            current_value: Current value
            connection_id: Connection identifier if applicable
            peer_id: Peer ID if applicable
            metadata: Additional event metadata

        """
        event_type = (
            ConnectionEventType.MEMORY_LIMIT_EXCEEDED
            if limit_type == "memory"
            else ConnectionEventType.RESOURCE_LIMIT_EXCEEDED
        )

        event = ConnectionEvent(
            event_type=event_type,
            connection_id=connection_id,
            peer_id=peer_id,
            metadata={
                **(metadata or {}),
                "limit_type": limit_type,
                "limit_value": limit_value,
                "current_value": current_value,
            },
        )

        await self.event_bus.publish(event)

    async def publish_stream_event(
        self,
        event_type: ConnectionEventType,
        connection_id: str,
        peer_id: ID,
        stream_id: str | None = None,
        protocol: str | None = None,
        direction: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a stream lifecycle event.

        Args:
            event_type: Type of stream event
            connection_id: Connection identifier
            peer_id: Peer ID
            stream_id: Stream identifier
            protocol: Stream protocol
            direction: Stream direction
            metadata: Additional event metadata

        """
        event = ConnectionEvent(
            event_type=event_type,
            connection_id=connection_id,
            peer_id=peer_id,
            metadata={
                **(metadata or {}),
                "stream_id": stream_id,
                "protocol": protocol,
                "direction": direction,
            },
        )

        await self.event_bus.publish(event)

    async def publish_peer_event(
        self,
        action: str,
        peer_id: ID,
        connection_id: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a peer-related event.

        Args:
            action: Peer action ("connected", "disconnected", "bypassed", "unbypassed")
            peer_id: Peer ID
            connection_id: Connection identifier if applicable
            metadata: Additional event metadata

        """
        event_type = (
            ConnectionEventType.PEER_CONNECTED
            if action == "connected"
            else ConnectionEventType.PEER_DISCONNECTED
            if action == "disconnected"
            else ConnectionEventType.PEER_BYPASSED
            if action == "bypassed"
            else ConnectionEventType.PEER_UNBYPASSED
        )

        event = ConnectionEvent(
            event_type=event_type,
            connection_id=connection_id,
            peer_id=peer_id,
            metadata={**(metadata or {}), "action": action},
        )

        await self.event_bus.publish(event)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get handler statistics.

        Returns:
            Dictionary of handler statistics

        """
        return {
            **self._stats,
            "event_bus_stats": self.event_bus.get_event_stats(),
        }

    def get_event_bus(self) -> ConnectionEventBus:
        """
        Get the event bus.

        Returns:
            Connection event bus

        """
        return self.event_bus

    def __str__(self) -> str:
        """String representation of lifecycle handler."""
        return (
            f"ConnectionLifecycleHandler("
            f"events_processed={self._stats['events_processed']}, "
            f"errors={self._stats['errors']})"
        )

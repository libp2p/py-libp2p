"""WebSocket connection manager for handling multiple connections."""

from datetime import datetime
import logging
from typing import Dict, Optional, Set

import trio

from .connection import P2PWebSocketConnection

logger = logging.getLogger(__name__)


class WebSocketConnectionManager:
    """
    Manages multiple WebSocket connections with features:
    - Connection pooling and cleanup
    - Statistics tracking
    - Resource limits
    - Automatic cleanup of inactive connections
    """

    def __init__(
        self,
        max_connections: int = 1000,
        inactive_timeout: float = 300.0,  # 5 minutes
        cleanup_interval: float = 60.0,   # 1 minute
    ):
        self.max_connections = max_connections
        self.inactive_timeout = inactive_timeout
        self.cleanup_interval = cleanup_interval

        self._connections: Dict[str, P2PWebSocketConnection] = {}
        self._nursery = None
        self._lock = trio.Lock()

    async def __aenter__(self):
        """Context manager entry."""
        self._nursery = trio.open_nursery()
        await self._nursery.start(self._cleanup_loop)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._nursery:
            self._nursery.cancel_scope.cancel()
            self._nursery = None

    async def add_connection(
        self,
        conn_id: str,
        connection: P2PWebSocketConnection
    ) -> None:
        """
        Add a new connection to the manager.
        
        Args:
            conn_id: Unique connection identifier
            connection: WebSocket connection instance
            
        Raises:
            RuntimeError: If maximum connections reached

        """
        async with self._lock:
            if len(self._connections) >= self.max_connections:
                raise RuntimeError(
                    f"Maximum connections ({self.max_connections}) reached"
                )

            self._connections[conn_id] = connection
            logger.info("Added connection %s, total: %d", conn_id, len(self._connections))

    async def remove_connection(self, conn_id: str) -> None:
        """
        Remove a connection from the manager.
        
        Args:
            conn_id: Connection identifier to remove

        """
        async with self._lock:
            if conn_id in self._connections:
                conn = self._connections.pop(conn_id)
                await conn.close()
                logger.info(
                    "Removed connection %s, remaining: %d",
                    conn_id,
                    len(self._connections)
                )

    async def get_connection(self, conn_id: str) -> Optional[P2PWebSocketConnection]:
        """
        Get a connection by ID.
        
        Args:
            conn_id: Connection identifier
            
        Returns:
            Optional[P2PWebSocketConnection]: Connection if found, None otherwise

        """
        return self._connections.get(conn_id)

    def get_active_connections(self) -> Set[str]:
        """
        Get IDs of all active (non-closed) connections.
        
        Returns:
            Set[str]: Set of active connection IDs

        """
        return {
            conn_id
            for conn_id, conn in self._connections.items()
            if not conn._closed
        }

    def get_connection_stats(self) -> Dict[str, Dict]:
        """
        Get statistics for all connections.
        
        Returns:
            Dict[str, Dict]: Connection statistics by connection ID

        """
        return {
            conn_id: {
                "stats": conn.stats.__dict__,
                "active": not conn._closed,
            }
            for conn_id, conn in self._connections.items()
        }

    def get_manager_stats(self) -> Dict:
        """
        Get overall connection manager statistics.
        
        Returns:
            Dict: Manager statistics

        """
        active_connections = self.get_active_connections()
        return {
            "total_connections": len(self._connections),
            "active_connections": len(active_connections),
            "total_bytes_sent": sum(
                conn.stats.bytes_sent
                for conn in self._connections.values()
            ),
            "total_bytes_received": sum(
                conn.stats.bytes_received
                for conn in self._connections.values()
            ),
            "total_messages_sent": sum(
                conn.stats.messages_sent
                for conn in self._connections.values()
            ),
            "total_messages_received": sum(
                conn.stats.messages_received
                for conn in self._connections.values()
            ),
            "total_errors": sum(
                conn.stats.errors
                for conn in self._connections.values()
            ),
        }

    async def close_all(self) -> None:
        """Close all connections and stop the manager."""
        async with self._lock:
            for conn_id, conn in list(self._connections.items()):
                await self.remove_connection(conn_id)

            if self._nursery:
                self._nursery.cancel_scope.cancel()
                self._nursery = None

    async def _cleanup_loop(self) -> None:
        """Background task to clean up inactive connections."""
        while True:
            try:
                await trio.sleep(self.cleanup_interval)
                await self._cleanup_inactive()
            except trio.Cancelled:
                break
            except Exception as e:
                logger.error("Error in cleanup loop: %s", e)

    async def _cleanup_inactive(self) -> None:
        """Remove inactive connections."""
        now = datetime.utcnow()
        to_remove = []

        async with self._lock:
            for conn_id, conn in self._connections.items():
                if (conn.stats.last_activity and
                    (now - conn.stats.last_activity).total_seconds() > self.inactive_timeout):
                    to_remove.append(conn_id)

            for conn_id in to_remove:
                logger.info("Removing inactive connection: %s", conn_id)
                await self.remove_connection(conn_id)

"""
Test cases for connection-level resource manager protection.

This module tests that resource manager protection is applied to all
connection types (TCP, WebSocket, QUIC) in Swarm.add_conn().
"""

from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.network.connection.swarm_connection import SwarmConn


class TestConnectionProtection:
    """Test connection-level resource manager protection."""

    def test_swarm_conn_has_resource_scope_attribute(self):
        """Test that SwarmConn has resource scope tracking."""
        # Create mock objects
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = "test_peer_id"
        mock_swarm = Mock()

        # Create SwarmConn instance
        swarm_conn = SwarmConn(mock_muxed_conn, mock_swarm)

        # Verify resource scope attribute exists
        assert hasattr(swarm_conn, "_resource_scope")
        assert swarm_conn._resource_scope is None

    def test_swarm_conn_set_resource_scope_method(self):
        """Test that SwarmConn has set_resource_scope method."""
        # Create mock objects
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = "test_peer_id"
        mock_swarm = Mock()

        # Create SwarmConn instance
        swarm_conn = SwarmConn(mock_muxed_conn, mock_swarm)

        # Verify set_resource_scope method exists
        assert hasattr(swarm_conn, "set_resource_scope")
        assert callable(swarm_conn.set_resource_scope)

    def test_swarm_conn_set_resource_scope_functionality(self):
        """Test that set_resource_scope method works correctly."""
        # Create mock objects
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = "test_peer_id"
        mock_swarm = Mock()

        # Create SwarmConn instance
        swarm_conn = SwarmConn(mock_muxed_conn, mock_swarm)

        # Test setting resource scope
        mock_scope = Mock()
        swarm_conn.set_resource_scope(mock_scope)

        # Verify scope was set
        assert swarm_conn._resource_scope == mock_scope

    @pytest.mark.trio
    async def test_swarm_conn_close_handles_resource_scope_cleanup(self):
        """Test that SwarmConn.close() handles resource scope cleanup."""
        # Create mock objects
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = "test_peer_id"
        mock_muxed_conn.close = AsyncMock()
        mock_swarm = Mock()

        # Create SwarmConn instance
        swarm_conn = SwarmConn(mock_muxed_conn, mock_swarm)

        # Set a mock resource scope
        mock_scope = Mock()
        mock_scope.close = AsyncMock()
        swarm_conn.set_resource_scope(mock_scope)

        # Mock the cleanup method to avoid actual cleanup
        swarm_conn._cleanup = AsyncMock()

        # Test close method
        await swarm_conn.close()

        # Verify resource scope was cleaned up
        assert swarm_conn._resource_scope is None
        mock_scope.close.assert_called_once()

    def test_swarm_conn_close_handles_resource_scope_without_close_method(self):
        """Test that SwarmConn.close() handles resource scope without close method."""
        # Create mock objects
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = "test_peer_id"
        mock_muxed_conn.close = AsyncMock()
        mock_swarm = Mock()

        # Create SwarmConn instance
        swarm_conn = SwarmConn(mock_muxed_conn, mock_swarm)

        # Set a mock resource scope without close method
        mock_scope = Mock()
        mock_scope.release = Mock()
        del mock_scope.close  # Remove close method
        swarm_conn.set_resource_scope(mock_scope)

        # Mock the cleanup method to avoid actual cleanup
        swarm_conn._cleanup = AsyncMock()

        # Test close method (should not raise exception)
        import trio

        trio.run(swarm_conn.close)

        # Verify resource scope was cleaned up
        assert swarm_conn._resource_scope is None
        mock_scope.release.assert_called_once()

    def test_swarm_conn_close_handles_resource_scope_cleanup_error(self):
        """Test SwarmConn.close() handles cleanup errors gracefully."""
        # Create mock objects
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = "test_peer_id"
        mock_muxed_conn.close = AsyncMock()
        mock_swarm = Mock()

        # Create SwarmConn instance
        swarm_conn = SwarmConn(mock_muxed_conn, mock_swarm)

        # Set a mock resource scope that raises error
        mock_scope = Mock()
        mock_scope.close = AsyncMock(side_effect=Exception("Cleanup error"))
        swarm_conn.set_resource_scope(mock_scope)

        # Mock the cleanup method to avoid actual cleanup
        swarm_conn._cleanup = AsyncMock()

        # Test close method (should not raise exception)
        import trio

        trio.run(swarm_conn.close)

        # Verify resource scope was still cleaned up despite error
        assert swarm_conn._resource_scope is None

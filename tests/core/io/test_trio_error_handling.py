"""
Test cases for trio.ClosedResourceError handling in I/O operations.

This module tests the graceful handling of trio.ClosedResourceError
and trio.BrokenResourceError in the TrioTCPStream implementation.
"""

from unittest.mock import AsyncMock, Mock

import pytest
import trio

from libp2p.io.trio import TrioTCPStream


class TestTrioErrorHandling:
    """Test trio error handling in I/O operations."""

    def test_trio_tcp_stream_creation(self):
        """Test that TrioTCPStream can be created."""
        # Create mock stream
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock()
        mock_stream.receive_some = AsyncMock()
        mock_stream.aclose = AsyncMock()

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        assert tcp_stream.stream == mock_stream
        assert hasattr(tcp_stream, "write_lock")

    @pytest.mark.trio
    async def test_write_handles_closed_resource_error(self):
        """Test that write() handles trio.ClosedResourceError gracefully."""
        # Create mock stream that raises ClosedResourceError
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock(
            side_effect=trio.ClosedResourceError("Socket closed")
        )

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test write with closed resource - should not raise exception
        await tcp_stream.write(b"test data")

        # Verify send_all was called
        mock_stream.send_all.assert_called_once_with(b"test data")

    @pytest.mark.trio
    async def test_write_handles_broken_resource_error(self):
        """Test that write() handles trio.BrokenResourceError gracefully."""
        # Create mock stream that raises BrokenResourceError
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock(
            side_effect=trio.BrokenResourceError("Socket broken")
        )

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test write with broken resource - should not raise exception
        await tcp_stream.write(b"test data")

        # Verify send_all was called
        mock_stream.send_all.assert_called_once_with(b"test data")

    @pytest.mark.trio
    async def test_write_handles_other_exceptions(self):
        """Test that write() still raises other exceptions."""
        # Create mock stream that raises a different exception
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock(side_effect=ValueError("Some other error"))

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test write with other exception - should raise the exception
        with pytest.raises(ValueError, match="Some other error"):
            await tcp_stream.write(b"test data")

    @pytest.mark.trio
    async def test_write_successful_operation(self):
        """Test that write() works normally when no errors occur."""
        # Create mock stream that works normally
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock()

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test successful write
        await tcp_stream.write(b"test data")

        # Verify send_all was called
        mock_stream.send_all.assert_called_once_with(b"test data")

    @pytest.mark.trio
    async def test_write_with_empty_data(self):
        """Test that write() handles empty data correctly."""
        # Create mock stream
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock()

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test write with empty data
        await tcp_stream.write(b"")

        # Verify send_all was called with empty data
        mock_stream.send_all.assert_called_once_with(b"")

    @pytest.mark.trio
    async def test_write_lock_prevents_concurrent_writes(self):
        """Test that write_lock prevents concurrent writes."""
        # Create mock stream
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock()

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test concurrent writes using trio nursery
        async def write_data(data):
            await tcp_stream.write(data)

        # Run concurrent writes using trio nursery
        async with trio.open_nursery() as nursery:
            nursery.start_soon(write_data, b"data1")
            nursery.start_soon(write_data, b"data2")
            nursery.start_soon(write_data, b"data3")

        # Verify send_all was called for each write
        assert mock_stream.send_all.call_count == 3

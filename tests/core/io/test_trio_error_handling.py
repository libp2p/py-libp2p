"""
Test cases for trio error handling in TrioTCPStream and RawConnection.

This module tests:
- ClosedResourceError is silently handled (local cleanup — backward compat)
- BrokenResourceError raises ConnectionClosedError (remote reset — issue #376)
- ConnectionClosedError propagates through RawConnection as RawConnError
- ConnectionClosedError has correct attributes (transport="tcp")
- ConnectionClosedError is a subclass of IOException (backward compat)
"""

from unittest.mock import AsyncMock, Mock

import pytest
import trio

from libp2p.io.exceptions import (
    ConnectionClosedError,
    IOException,
)
from libp2p.io.trio import TrioTCPStream
from libp2p.network.connection.exceptions import (
    RawConnError,
)
from libp2p.network.connection.raw_connection import (
    RawConnection,
)


class TestTrioErrorHandling:
    """Test trio error handling in I/O operations."""

    # ---- creation ----

    def test_trio_tcp_stream_creation(self) -> None:
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

    # ---- write() tests ----

    @pytest.mark.trio
    async def test_write_handles_closed_resource_error(self) -> None:
        """
        Test that write() silently handles trio.ClosedResourceError.

        ClosedResourceError means local code closed the resource. During
        cleanup/teardown this should return silently for backward compat.
        """
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
    async def test_write_raises_on_broken_resource_error(self) -> None:
        """
        Test that write() raises ConnectionClosedError on BrokenResourceError.

        BrokenResourceError means the remote peer reset the connection.
        This should be surfaced as ConnectionClosedError, not swallowed.
        """
        # Create mock stream that raises BrokenResourceError
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock(
            side_effect=trio.BrokenResourceError("Socket broken")
        )

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Should raise ConnectionClosedError with transport="tcp"
        with pytest.raises(ConnectionClosedError) as exc_info:
            await tcp_stream.write(b"test data")

        exc = exc_info.value
        assert exc.transport == "tcp"
        assert "Socket broken" in str(exc)

        # Verify send_all was called
        mock_stream.send_all.assert_called_once_with(b"test data")

    @pytest.mark.trio
    async def test_write_handles_other_exceptions(self) -> None:
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
    async def test_write_successful_operation(self) -> None:
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
    async def test_write_with_empty_data(self) -> None:
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
    async def test_write_lock_prevents_concurrent_writes(self) -> None:
        """Test that write_lock prevents concurrent writes."""
        # Create mock stream
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock()

        # Create TrioTCPStream instance
        tcp_stream = TrioTCPStream(mock_stream)

        # Test concurrent writes using trio nursery
        async def write_data(data: bytes) -> None:
            await tcp_stream.write(data)

        # Run concurrent writes using trio nursery
        async with trio.open_nursery() as nursery:
            nursery.start_soon(write_data, b"data1")
            nursery.start_soon(write_data, b"data2")
            nursery.start_soon(write_data, b"data3")

        # Verify send_all was called for each write
        assert mock_stream.send_all.call_count == 3

    # ---- read() tests ----

    @pytest.mark.trio
    async def test_read_handles_closed_resource_error(self) -> None:
        """
        Test that read() returns b'' on trio.ClosedResourceError.

        ClosedResourceError means local code closed the resource. During
        cleanup/teardown this should return empty bytes silently.
        """
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(
            side_effect=trio.ClosedResourceError("Socket closed")
        )

        tcp_stream = TrioTCPStream(mock_stream)

        result = await tcp_stream.read(1024)

        assert result == b""
        mock_stream.receive_some.assert_called_once_with(1024)

    @pytest.mark.trio
    async def test_read_raises_on_broken_resource_error(self) -> None:
        """
        Test that read() raises ConnectionClosedError on BrokenResourceError.

        BrokenResourceError means the remote peer reset the connection.
        This should be surfaced as ConnectionClosedError, not return b''.
        """
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(
            side_effect=trio.BrokenResourceError("Connection reset by peer")
        )

        tcp_stream = TrioTCPStream(mock_stream)

        with pytest.raises(ConnectionClosedError) as exc_info:
            await tcp_stream.read(1024)

        exc = exc_info.value
        assert exc.transport == "tcp"
        assert "Connection reset by peer" in str(exc)

    @pytest.mark.trio
    async def test_read_handles_other_exceptions(self) -> None:
        """Test that read() still raises other exceptions."""
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(side_effect=ValueError("Some other error"))

        tcp_stream = TrioTCPStream(mock_stream)

        with pytest.raises(ValueError, match="Some other error"):
            await tcp_stream.read(1024)

    @pytest.mark.trio
    async def test_read_successful_operation(self) -> None:
        """Test that read() works normally when no errors occur."""
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(return_value=b"response data")

        tcp_stream = TrioTCPStream(mock_stream)

        result = await tcp_stream.read(1024)

        assert result == b"response data"
        mock_stream.receive_some.assert_called_once_with(1024)

    @pytest.mark.trio
    async def test_read_zero_bytes_returns_empty(self) -> None:
        """Test that read(0) returns b'' without touching the stream."""
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock()

        tcp_stream = TrioTCPStream(mock_stream)

        result = await tcp_stream.read(0)

        assert result == b""
        mock_stream.receive_some.assert_not_called()

    @pytest.mark.trio
    async def test_read_none_passes_none_to_stream(self) -> None:
        """Test that read(None) passes None to receive_some."""
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(return_value=b"data")

        tcp_stream = TrioTCPStream(mock_stream)

        result = await tcp_stream.read(None)

        assert result == b"data"
        mock_stream.receive_some.assert_called_once_with(None)

    # ---- RawConnection propagation tests ----

    @pytest.mark.trio
    async def test_raw_conn_read_raises_on_broken_resource(self) -> None:
        """
        Test full error propagation chain for read.

        BrokenResourceError -> ConnectionClosedError -> RawConnError.
        When TrioTCPStream raises ConnectionClosedError (subclass of
        IOException), RawConnection catches it and re-raises as RawConnError.
        """
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(
            side_effect=trio.BrokenResourceError("Connection reset")
        )

        tcp_stream = TrioTCPStream(mock_stream)
        raw_conn = RawConnection(tcp_stream, initiator=True)

        with pytest.raises(RawConnError) as exc_info:
            await raw_conn.read(1024)

        # Verify the chain: RawConnError wraps ConnectionClosedError
        cause = exc_info.value.__cause__
        assert isinstance(cause, ConnectionClosedError)
        assert cause.transport == "tcp"

    @pytest.mark.trio
    async def test_raw_conn_write_raises_on_broken_resource(self) -> None:
        """
        Test full error propagation chain for write.

        BrokenResourceError -> ConnectionClosedError -> RawConnError.
        Same propagation test for the write path.
        """
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock(
            side_effect=trio.BrokenResourceError("Broken pipe")
        )

        tcp_stream = TrioTCPStream(mock_stream)
        raw_conn = RawConnection(tcp_stream, initiator=True)

        with pytest.raises(RawConnError) as exc_info:
            await raw_conn.write(b"test data")

        # Verify the chain: RawConnError wraps ConnectionClosedError
        cause = exc_info.value.__cause__
        assert isinstance(cause, ConnectionClosedError)
        assert cause.transport == "tcp"

    # ---- ConnectionClosedError hierarchy and attribute tests ----

    @pytest.mark.trio
    async def test_connection_closed_error_is_subclass_of_ioexception(self) -> None:
        """
        Verify ConnectionClosedError is catchable as IOException.

        This ensures existing ``except IOException`` handlers still
        catch it, maintaining backward compatibility.
        """
        mock_stream = Mock()
        mock_stream.receive_some = AsyncMock(
            side_effect=trio.BrokenResourceError("Reset")
        )

        tcp_stream = TrioTCPStream(mock_stream)

        # Should be catchable as IOException (backward compat)
        with pytest.raises(IOException):
            await tcp_stream.read(1024)

    @pytest.mark.trio
    async def test_connection_closed_error_attributes_on_write(self) -> None:
        """Verify ConnectionClosedError from write has correct structured attributes."""
        mock_stream = Mock()
        mock_stream.send_all = AsyncMock(
            side_effect=trio.BrokenResourceError("Broken pipe")
        )

        tcp_stream = TrioTCPStream(mock_stream)

        with pytest.raises(ConnectionClosedError) as exc_info:
            await tcp_stream.write(b"data")

        exc = exc_info.value
        assert exc.transport == "tcp"
        # TCP has no close codes or reasons (unlike WebSocket)
        assert exc.close_code is None
        assert exc.close_reason == ""

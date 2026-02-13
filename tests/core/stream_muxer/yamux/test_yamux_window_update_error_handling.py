"""
Unit tests for yamux window update error handling.

This test directly tests the send_window_update() method's error handling
without requiring full yamux protocol simulation.
"""

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.io.exceptions import IOException
from libp2p.network.connection.exceptions import RawConnError
from libp2p.stream_muxer.yamux.yamux import YamuxStream

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_send_window_update_handles_connection_closed_error():
    """
    Test that send_window_update gracefully handles connection closure errors.

    This directly tests the fix for the Nim WebSocket issue where:
    - Connection closes immediately after sending data
    - Window update write fails with connection closure error
    - Error should be caught and logged, not raised
    """
    # Create a mock secured connection that raises IOException on write
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(
        side_effect=IOException("Connection closed by peer")
    )

    # Create a YamuxStream (we need minimal setup)
    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Call send_window_update - should not raise despite connection error
    # The error should be caught and logged internally
    await stream.send_window_update(32)

    # Verify write was attempted
    assert mock_conn.secured_conn.write.called

    # Verify no exception was raised (test passes if we get here)


@pytest.mark.trio
async def test_send_window_update_handles_raw_conn_error():
    """
    Test that send_window_update handles RawConnError gracefully.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(
        side_effect=RawConnError("Connection closed")
    )

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should not raise
    await stream.send_window_update(32)

    assert mock_conn.secured_conn.write.called


@pytest.mark.trio
async def test_send_window_update_handles_various_closure_messages():
    """
    Test that send_window_update handles various connection closure error messages.
    """
    closure_messages = [
        "Connection closed by peer",
        "connection closed",
        "WebSocket connection closed",
        "Connection is closed",
        "WebSocket connection closed by peer during write operation",
    ]

    for error_msg in closure_messages:
        mock_conn = Mock()
        mock_conn.secured_conn = AsyncMock()
        mock_conn.secured_conn.write = AsyncMock(side_effect=IOException(error_msg))

        stream_id = 1
        stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

        # Should not raise for any of these messages
        await stream.send_window_update(32)

        assert mock_conn.secured_conn.write.called


@pytest.mark.trio
async def test_send_window_update_raises_unexpected_errors():
    """
    Test that unexpected errors (not connection closure) are still raised.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(side_effect=ValueError("Unexpected error"))

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should raise unexpected error
    with pytest.raises(ValueError, match="Unexpected error"):
        await stream.send_window_update(32)


@pytest.mark.trio
async def test_send_window_update_succeeds_when_connection_open():
    """
    Test that send_window_update succeeds normally when connection is open.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock()  # No error

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should succeed without error
    await stream.send_window_update(32)

    # Verify write was called with correct header
    assert mock_conn.secured_conn.write.called
    call_args = mock_conn.secured_conn.write.call_args[0][0]
    assert len(call_args) == 12  # Yamux header is 12 bytes
    # Verify it's a window update (type 0x1)
    assert call_args[1] == 0x1


@pytest.mark.trio
async def test_send_window_update_skips_zero_increment():
    """
    Test that send_window_update skips sending when increment is zero or negative.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should skip for zero increment
    await stream.send_window_update(0)
    assert not mock_conn.secured_conn.write.called

    # Should skip for negative increment
    await stream.send_window_update(-1)
    assert not mock_conn.secured_conn.write.called


@pytest.mark.trio
async def test_send_window_update_raises_non_closure_io_exception():
    """
    Test that IOException with non-closure message is still raised.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(side_effect=IOException("Disk full error"))

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should raise since "Disk full error" doesn't match closure patterns
    with pytest.raises(IOException, match="Disk full error"):
        await stream.send_window_update(32)

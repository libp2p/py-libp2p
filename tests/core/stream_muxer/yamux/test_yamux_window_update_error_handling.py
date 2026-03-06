"""
Unit tests for yamux window update error handling.

This test directly tests the send_window_update() method's error handling
without requiring full yamux protocol simulation.

The yamux muxer uses two strategies to detect connection closure during
window updates:

1. **Typed exception** — ``ConnectionClosedError`` (raised by the WebSocket
   transport) is caught by type.  No string matching needed.
2. **String-matching fallback** — ``RawConnError`` / plain ``IOException``
   from transports that haven't migrated to ``ConnectionClosedError`` yet
   (e.g. TCP) are matched against known closure keywords.
"""

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.io.exceptions import ConnectionClosedError, IOException
from libp2p.network.connection.exceptions import RawConnError
from libp2p.stream_muxer.yamux.yamux import YamuxStream

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path 1 — ConnectionClosedError (typed, no string matching)
# ---------------------------------------------------------------------------


@pytest.mark.trio
async def test_send_window_update_handles_connection_closed_error():
    """
    Test that send_window_update gracefully handles ConnectionClosedError.

    This is the primary path for WebSocket connections: the transport
    raises a typed ``ConnectionClosedError`` which yamux catches directly
    by type — no string matching required.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(
        side_effect=ConnectionClosedError(
            "WebSocket connection closed by peer during write operation",
            close_code=1000,
            close_reason="Normal closure",
            transport="websocket",
        )
    )

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should not raise — ConnectionClosedError is handled gracefully
    await stream.send_window_update(32)

    assert mock_conn.secured_conn.write.called


@pytest.mark.trio
async def test_send_window_update_handles_connection_closed_error_any_message():
    """
    ConnectionClosedError is caught by type regardless of the message content.
    This is the key improvement over string matching — the message can be
    anything without affecting behavior.
    """
    unusual_messages = [
        "something completely unrelated",
        "",
        "no closure keywords here!",
    ]

    for msg in unusual_messages:
        mock_conn = Mock()
        mock_conn.secured_conn = AsyncMock()
        mock_conn.secured_conn.write = AsyncMock(
            side_effect=ConnectionClosedError(msg, close_code=1000)
        )

        stream = YamuxStream(1, mock_conn, is_initiator=True)
        await stream.send_window_update(32)  # Should not raise
        assert mock_conn.secured_conn.write.called


# ---------------------------------------------------------------------------
# Path 2 — String-matching fallback (RawConnError / plain IOException)
# ---------------------------------------------------------------------------


@pytest.mark.trio
async def test_send_window_update_handles_raw_conn_error():
    """
    Test that send_window_update handles RawConnError with closure message
    gracefully (string-matching fallback for TCP transport).
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(
        side_effect=RawConnError("Connection closed")
    )

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    # Should not raise — falls through to string-matching fallback
    await stream.send_window_update(32)

    assert mock_conn.secured_conn.write.called


@pytest.mark.trio
async def test_send_window_update_handles_various_closure_messages():
    """
    Test that the string-matching fallback handles various closure messages
    from transports that don't yet raise ConnectionClosedError.
    """
    closure_messages = [
        "Connection closed by peer",
        "connection closed",
        "Connection is closed",
        "closed by peer unexpectedly",
    ]

    for error_msg in closure_messages:
        mock_conn = Mock()
        mock_conn.secured_conn = AsyncMock()
        mock_conn.secured_conn.write = AsyncMock(side_effect=IOException(error_msg))

        stream = YamuxStream(1, mock_conn, is_initiator=True)

        # Should not raise for any of these messages
        await stream.send_window_update(32)
        assert mock_conn.secured_conn.write.called


# ---------------------------------------------------------------------------
# Errors that should NOT be suppressed
# ---------------------------------------------------------------------------


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

    with pytest.raises(ValueError, match="Unexpected error"):
        await stream.send_window_update(32)


@pytest.mark.trio
async def test_send_window_update_raises_non_closure_io_exception():
    """
    Test that plain IOException with non-closure message is still raised.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()
    mock_conn.secured_conn.write = AsyncMock(side_effect=IOException("Disk full error"))

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    with pytest.raises(IOException, match="Disk full error"):
        await stream.send_window_update(32)


# ---------------------------------------------------------------------------
# Normal operation
# ---------------------------------------------------------------------------


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

    await stream.send_window_update(32)

    assert mock_conn.secured_conn.write.called
    call_args = mock_conn.secured_conn.write.call_args[0][0]
    assert len(call_args) == 12  # Yamux header is 12 bytes
    assert call_args[1] == 0x1  # Window update type


@pytest.mark.trio
async def test_send_window_update_skips_zero_increment():
    """
    Test that send_window_update skips sending when increment is zero or negative.
    """
    mock_conn = Mock()
    mock_conn.secured_conn = AsyncMock()

    stream_id = 1
    stream = YamuxStream(stream_id, mock_conn, is_initiator=True)

    await stream.send_window_update(0)
    assert not mock_conn.secured_conn.write.called

    await stream.send_window_update(-1)
    assert not mock_conn.secured_conn.write.called

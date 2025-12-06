"""Tests for WebRTC stream deadline functionality."""

import pytest
import trio
from datetime import datetime, timedelta
from libp2p.transport.webrtc.private_to_public.stream import (
    WebRTCStream,
    StreamDirection,
)
from libp2p.transport.webrtc.exception import (
    WebRTCStreamTimeoutError,
    WebRTCStreamClosedError,
)

class MockRTCDataChannel:
    """Mock RTCDataChannel for testing."""
    
    def __init__(self):
        self.id = 1
        self.readyState = "open"
        self.bufferedAmount = 0
        self._listeners = {}
    
    def on(self, event, handler):
        self._listeners[event] = handler
    
    def send(self, data):
        pass
    
    def close(self):
        self.readyState = "closed"


@pytest.mark.trio
async def test_set_deadline_basic():
    """Test that deadline can be set on stream."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # Call set_deadline (NOT async)
    result = stream.set_deadline(ttl=10)
    
    assert result is True
    assert stream.read_deadline is not None
    assert stream.write_deadline is not None
    assert isinstance(stream.read_deadline, datetime)
    
    await stream.close()


@pytest.mark.trio
async def test_set_deadline_on_closed_stream():
    """Test setting deadline on closed stream returns False."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    await stream.close()
    
    # Should return False
    result = stream.set_deadline(ttl=10)
    assert result is False


@pytest.mark.trio
async def test_read_deadline_exceeded():
    """Test that read raises when deadline exceeded."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # Set deadline to past time (negative = already expired)
    result = stream.set_deadline(ttl=-1)
    assert result is True
    
    # Should raise on read
    with pytest.raises(WebRTCStreamTimeoutError):
        await stream.read()


@pytest.mark.trio
async def test_write_deadline_exceeded():
    """Test that write raises when deadline exceeded."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # Set deadline to past time
    result = stream.set_deadline(ttl=-1)
    assert result is True
    
    # Should raise on write
    with pytest.raises(WebRTCStreamTimeoutError):
        await stream.write(b"test data")


@pytest.mark.trio
async def test_deadline_properties():
    """Test deadline property accessors."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # Initially None
    assert stream.read_deadline is None
    assert stream.write_deadline is None
    
    # After setting
    stream.set_deadline(ttl=30)
    
    assert stream.read_deadline is not None
    assert stream.write_deadline is not None
    assert stream.read_deadline == stream.write_deadline
    
    await stream.close()


@pytest.mark.trio
async def test_deadline_cleanup_on_close():
    """Test deadline cleanup when stream closes."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    stream.set_deadline(ttl=100)
    
    # Verify deadline is set
    assert stream.read_deadline is not None
    
    # Close stream
    await stream.close()
    
    # Deadline should be cleared
    assert stream.read_deadline is None
    assert stream.write_deadline is None


@pytest.mark.trio
async def test_remaining_deadline():
    """Test getting remaining time until deadline."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # No deadline set
    remaining = stream._get_remaining_deadline()
    assert remaining is None
    
    # Set 10 second deadline
    stream.set_deadline(ttl=10)
    
    remaining = stream._get_remaining_deadline()
    assert remaining is not None
    assert 9 < remaining <= 10  # Should be close to 10 seconds
    
    await stream.close()


@pytest.mark.trio
async def test_deadline_multiple_sets():
    """Test setting deadline multiple times."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # Set first deadline
    stream.set_deadline(ttl=10)
    first_deadline = stream.read_deadline
    
    await trio.sleep(0.1)
    
    # Set second deadline
    stream.set_deadline(ttl=20)
    second_deadline = stream.read_deadline
    
    # Second should be later
    assert second_deadline > first_deadline
    
    await stream.close()


@pytest.mark.trio
async def test_deadline_with_actual_operations():
    """Test that deadline actually prevents operations."""
    channel = MockRTCDataChannel()
    stream = WebRTCStream(1, StreamDirection.OUTBOUND, channel)
    
    # Set very short deadline
    stream.set_deadline(ttl=0.001)  # 1ms
    
    # Wait for it to expire
    await trio.sleep(0.01)
    
    # Now operations should fail
    with pytest.raises(WebRTCStreamTimeoutError):
        await stream.read(100)
    
    await stream.close()

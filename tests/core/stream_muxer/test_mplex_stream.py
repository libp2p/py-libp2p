import pytest
import trio
from trio.testing import (
    wait_all_tasks_blocked,
)

from libp2p.stream_muxer.mplex.exceptions import (
    MplexStreamClosed,
    MplexStreamEOF,
    MplexStreamReset,
    MuxedConnUnavailable,
)
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_MESSAGE_CHANNEL_SIZE,
)
from libp2p.tools.constants import (
    MAX_READ_LEN,
)

DATA = b"data_123"


@pytest.mark.trio
async def test_mplex_stream_read_write(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.write(DATA)
    assert (await stream_1.read(MAX_READ_LEN)) == DATA


@pytest.mark.trio
async def test_mplex_stream_full_buffer(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    # Test: The message channel is of size `MPLEX_MESSAGE_CHANNEL_SIZE`.
    #   It should be fine to read even there are already `MPLEX_MESSAGE_CHANNEL_SIZE`
    #   messages arriving.
    for _ in range(MPLEX_MESSAGE_CHANNEL_SIZE):
        await stream_0.write(DATA)
    await wait_all_tasks_blocked()
    # Sanity check
    assert MAX_READ_LEN >= MPLEX_MESSAGE_CHANNEL_SIZE * len(DATA)
    assert (await stream_1.read(MAX_READ_LEN)) == MPLEX_MESSAGE_CHANNEL_SIZE * DATA

    # Test: Read after `MPLEX_MESSAGE_CHANNEL_SIZE + 1` messages has arrived, which
    #   exceeds the channel size. The stream should have been reset.
    for _ in range(MPLEX_MESSAGE_CHANNEL_SIZE + 1):
        await stream_0.write(DATA)
    await wait_all_tasks_blocked()
    with pytest.raises(MplexStreamReset):
        await stream_1.read(MAX_READ_LEN)


@pytest.mark.trio
async def test_mplex_stream_pair_read_until_eof(mplex_stream_pair):
    read_bytes = bytearray()
    stream_0, stream_1 = mplex_stream_pair

    async def read_until_eof():
        read_bytes.extend(await stream_1.read())

    expected_data = bytearray()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_until_eof)
        # Test: `read` doesn't return before `close` is called.
        await stream_0.write(DATA)
        expected_data.extend(DATA)
        await trio.sleep(0.01)
        assert len(read_bytes) == 0
        # Test: `read` doesn't return before `close` is called.
        await stream_0.write(DATA)
        expected_data.extend(DATA)
        await trio.sleep(0.01)
        assert len(read_bytes) == 0

        # Test: Close the stream, `read` returns, and receive previous sent data.
        await stream_0.close()

    assert read_bytes == expected_data


@pytest.mark.trio
async def test_mplex_stream_read_after_remote_closed(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    assert not stream_1.event_remote_closed.is_set()
    await stream_0.write(DATA)
    assert not stream_0.event_local_closed.is_set()
    await trio.sleep(0.01)
    await wait_all_tasks_blocked()
    await stream_0.close()
    assert stream_0.event_local_closed.is_set()
    await trio.sleep(0.01)
    await wait_all_tasks_blocked()
    assert stream_1.event_remote_closed.is_set()
    assert (await stream_1.read(MAX_READ_LEN)) == DATA
    with pytest.raises(MplexStreamEOF):
        await stream_1.read(MAX_READ_LEN)


@pytest.mark.trio
async def test_mplex_stream_read_after_local_reset(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.reset()
    with pytest.raises(MplexStreamReset):
        await stream_0.read(MAX_READ_LEN)


@pytest.mark.trio
async def test_mplex_stream_read_after_remote_reset(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.write(DATA)
    await stream_0.reset()
    # Sleep to let `stream_1` receive the message.
    await trio.sleep(0.1)
    await wait_all_tasks_blocked()
    with pytest.raises(MplexStreamReset):
        await stream_1.read(MAX_READ_LEN)


@pytest.mark.trio
async def test_mplex_stream_read_after_remote_closed_and_reset(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.write(DATA)
    await stream_0.close()
    await stream_0.reset()
    # Sleep to let `stream_1` receive the message.
    await trio.sleep(0.01)
    assert (await stream_1.read(MAX_READ_LEN)) == DATA


@pytest.mark.trio
async def test_mplex_stream_write_after_local_closed(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.write(DATA)
    await stream_0.close()
    with pytest.raises(MplexStreamClosed):
        await stream_0.write(DATA)


@pytest.mark.trio
async def test_mplex_stream_write_after_local_reset(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.reset()
    with pytest.raises(MplexStreamClosed):
        await stream_0.write(DATA)


@pytest.mark.trio
async def test_mplex_stream_write_after_remote_reset(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_1.reset()
    await trio.sleep(0.01)
    with pytest.raises(MplexStreamClosed):
        await stream_0.write(DATA)


@pytest.mark.trio
async def test_mplex_stream_both_close(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    # Flags are not set initially.
    assert not stream_0.event_local_closed.is_set()
    assert not stream_1.event_local_closed.is_set()
    assert not stream_0.event_remote_closed.is_set()
    assert not stream_1.event_remote_closed.is_set()
    # Streams are present in their `mplex_conn`.
    assert stream_0 in stream_0.muxed_conn.streams.values()
    assert stream_1 in stream_1.muxed_conn.streams.values()

    # Test: Close one side.
    await stream_0.close()
    await trio.sleep(0.01)

    assert stream_0.event_local_closed.is_set()
    assert not stream_1.event_local_closed.is_set()
    assert not stream_0.event_remote_closed.is_set()
    assert stream_1.event_remote_closed.is_set()
    # Streams are still present in their `mplex_conn`.
    assert stream_0 in stream_0.muxed_conn.streams.values()
    assert stream_1 in stream_1.muxed_conn.streams.values()

    # Test: Close the other side.
    await stream_1.close()
    await wait_all_tasks_blocked()
    # Both sides are closed.
    assert stream_0.event_local_closed.is_set()
    assert stream_1.event_local_closed.is_set()
    assert stream_0.event_remote_closed.is_set()
    assert stream_1.event_remote_closed.is_set()
    # Streams are removed from their `mplex_conn`.
    assert stream_0 not in stream_0.muxed_conn.streams.values()
    assert stream_1 not in stream_1.muxed_conn.streams.values()

    # Test: Reset after both close.
    await stream_0.reset()


@pytest.mark.trio
async def test_mplex_stream_reset(mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair
    await stream_0.reset()
    await trio.sleep(0.01)

    # Both sides are closed.
    assert stream_0.event_local_closed.is_set()
    assert stream_1.event_local_closed.is_set()
    assert stream_0.event_remote_closed.is_set()
    assert stream_1.event_remote_closed.is_set()
    # Streams are removed from their `mplex_conn`.
    assert stream_0 not in stream_0.muxed_conn.streams.values()
    assert stream_1 not in stream_1.muxed_conn.streams.values()

    # `close` should do nothing.
    await stream_0.close()
    await stream_1.close()
    # `reset` should do nothing as well.
    await stream_0.reset()
    await stream_1.reset()


@pytest.mark.trio
async def test_mplex_stream_close_timeout(monkeypatch, mplex_stream_pair):
    stream_0, stream_1 = mplex_stream_pair

    # (simulate hanging)
    async def fake_send_message(*args, **kwargs):
        await trio.sleep_forever()

    monkeypatch.setattr(stream_0.muxed_conn, "send_message", fake_send_message)

    with pytest.raises(TimeoutError):
        await stream_0.close()


@pytest.mark.trio
async def test_mplex_stream_close_mux_unavailable(monkeypatch, mplex_stream_pair):
    stream_0, _ = mplex_stream_pair

    # Patch send_message to raise MuxedConnUnavailable
    def raise_unavailable(*args, **kwargs):
        raise MuxedConnUnavailable("Simulated conn drop")

    monkeypatch.setattr(stream_0.muxed_conn, "send_message", raise_unavailable)

    # Case 1: Mplex is shutting down — should not raise
    stream_0.muxed_conn.event_shutting_down.set()
    await stream_0.close()  # Should NOT raise

    # Case 2: Mplex is NOT shutting down — should raise RuntimeError
    stream_0.event_local_closed = trio.Event()  # Reset since it was set in first call
    stream_0.muxed_conn.event_shutting_down = trio.Event()  # Unset the shutdown flag

    with pytest.raises(RuntimeError, match="Failed to send close message"):
        await stream_0.close()


# ========== Deadline Tests ==========


@pytest.mark.trio
async def test_mplex_stream_read_deadline_timeout(mplex_stream_pair):
    """Test that read operation times out when deadline is exceeded."""
    stream_0, stream_1 = mplex_stream_pair

    # Set a short read deadline
    stream_1.set_read_deadline(0.5)

    # Try to read without any data being sent - should timeout
    with pytest.raises(
        TimeoutError, match="Read operation timed out after 0.5 seconds"
    ):
        await stream_1.read(MAX_READ_LEN)


@pytest.mark.trio
async def test_mplex_stream_read_within_deadline(mplex_stream_pair):
    """Test that read operation succeeds when completed within deadline."""
    stream_0, stream_1 = mplex_stream_pair

    # Set a generous read deadline
    stream_1.set_read_deadline(5)

    # Send data and read it - should succeed
    await stream_0.write(DATA)
    result = await stream_1.read(MAX_READ_LEN)
    assert result == DATA


@pytest.mark.trio
async def test_mplex_stream_read_deadline_none(mplex_stream_pair):
    """Test that read operation with no deadline works as before."""
    stream_0, stream_1 = mplex_stream_pair

    # Ensure read_deadline is None (default)
    assert stream_1.read_deadline is None

    # Send data and read it
    await stream_0.write(DATA)
    result = await stream_1.read(MAX_READ_LEN)
    assert result == DATA


@pytest.mark.trio
async def test_mplex_stream_write_deadline_timeout(mplex_stream_pair, monkeypatch):
    """Test that write operation times out when deadline is exceeded."""
    stream_0, stream_1 = mplex_stream_pair

    # Set a short write deadline
    stream_0.set_write_deadline(0.5)

    # Mock send_message to simulate a hanging write
    async def slow_send_message(*args, **kwargs):
        await trio.sleep(2)  # Longer than deadline

    monkeypatch.setattr(stream_0.muxed_conn, "send_message", slow_send_message)

    # Try to write - should timeout
    with pytest.raises(
        TimeoutError, match="Write operation timed out after 0.5 seconds"
    ):
        await stream_0.write(DATA)


@pytest.mark.trio
async def test_mplex_stream_write_within_deadline(mplex_stream_pair):
    """Test that write operation succeeds when completed within deadline."""
    stream_0, stream_1 = mplex_stream_pair

    # Set a generous write deadline
    stream_0.set_write_deadline(5)

    # Write data - should succeed
    await stream_0.write(DATA)
    result = await stream_1.read(MAX_READ_LEN)
    assert result == DATA


@pytest.mark.trio
async def test_mplex_stream_write_deadline_none(mplex_stream_pair):
    """Test that write operation with no deadline works as before."""
    stream_0, stream_1 = mplex_stream_pair

    # Ensure write_deadline is None (default)
    assert stream_0.write_deadline is None

    # Write and read data
    await stream_0.write(DATA)
    result = await stream_1.read(MAX_READ_LEN)
    assert result == DATA


@pytest.mark.trio
async def test_mplex_stream_set_deadline_sets_both(mplex_stream_pair):
    """Test that set_deadline sets both read and write deadlines."""
    stream_0, stream_1 = mplex_stream_pair

    # Set deadline for both operations
    assert stream_0.set_deadline(30) is True
    assert stream_0.read_deadline == 30
    assert stream_0.write_deadline == 30

    # Should be able to update it
    assert stream_0.set_deadline(60) is True
    assert stream_0.read_deadline == 60
    assert stream_0.write_deadline == 60


@pytest.mark.trio
async def test_mplex_stream_set_read_deadline_only(mplex_stream_pair):
    """Test that set_read_deadline only sets read deadline."""
    stream_0, stream_1 = mplex_stream_pair

    # Set only read deadline
    assert stream_0.set_read_deadline(30) is True
    assert stream_0.read_deadline == 30
    assert stream_0.write_deadline is None


@pytest.mark.trio
async def test_mplex_stream_set_write_deadline_only(mplex_stream_pair):
    """Test that set_write_deadline only sets write deadline."""
    stream_0, stream_1 = mplex_stream_pair

    # Set only write deadline
    assert stream_0.set_write_deadline(30) is True
    assert stream_0.write_deadline == 30
    assert stream_0.read_deadline is None


@pytest.mark.trio
async def test_mplex_stream_deadline_independent(mplex_stream_pair):
    """Test that read and write deadlines can be set independently."""
    stream_0, stream_1 = mplex_stream_pair

    # Set different deadlines
    stream_0.set_read_deadline(10)
    stream_0.set_write_deadline(20)

    assert stream_0.read_deadline == 10
    assert stream_0.write_deadline == 20


@pytest.mark.trio
async def test_mplex_stream_read_deadline_with_reset_stream(mplex_stream_pair):
    """Test that read deadline doesn't interfere with stream reset detection."""
    stream_0, stream_1 = mplex_stream_pair

    # Set read deadline
    stream_1.set_read_deadline(5)

    # Reset the stream
    await stream_1.reset()

    # Should raise MplexStreamReset, not TimeoutError
    with pytest.raises(MplexStreamReset):
        await stream_1.read(MAX_READ_LEN)


@pytest.mark.trio
async def test_mplex_stream_write_deadline_with_closed_stream(mplex_stream_pair):
    """Test that write deadline doesn't interfere with closed stream detection."""
    stream_0, stream_1 = mplex_stream_pair

    # Set write deadline
    stream_0.set_write_deadline(5)

    # Close the stream
    await stream_0.close()

    # Should raise MplexStreamClosed, not TimeoutError
    with pytest.raises(MplexStreamClosed):
        await stream_0.write(DATA)


@pytest.mark.trio
async def test_mplex_stream_read_deadline_until_eof(mplex_stream_pair):
    """Test that read deadline works with read(None) - read until EOF."""
    stream_0, stream_1 = mplex_stream_pair

    # Set a generous deadline for reading until EOF
    stream_1.set_read_deadline(2)

    async def read_until_eof():
        return await stream_1.read()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_until_eof)
        await stream_0.write(DATA)
        await stream_0.close()

    # The read should complete successfully


@pytest.mark.trio
async def test_mplex_stream_deadline_update(mplex_stream_pair):
    """Test that deadlines can be updated multiple times."""
    stream_0, stream_1 = mplex_stream_pair

    # Initial deadline
    stream_0.set_deadline(10)
    assert stream_0.read_deadline == 10
    assert stream_0.write_deadline == 10

    # Update to shorter deadline
    stream_0.set_deadline(5)
    assert stream_0.read_deadline == 5
    assert stream_0.write_deadline == 5

    # Update individual deadlines
    stream_0.set_read_deadline(15)
    stream_0.set_write_deadline(20)
    assert stream_0.read_deadline == 15
    assert stream_0.write_deadline == 20


@pytest.mark.trio
async def test_mplex_stream_concurrent_operations_with_deadlines(mplex_stream_pair):
    """Test that deadlines work correctly with concurrent read/write operations."""
    stream_0, stream_1 = mplex_stream_pair

    # Set deadlines
    stream_0.set_write_deadline(5)
    stream_1.set_read_deadline(5)

    # Concurrent write and read
    async def writer():
        for i in range(5):
            await stream_0.write(DATA)
            await trio.sleep(0.01)

    async def reader():
        for i in range(5):
            result = await stream_1.read(len(DATA))
            assert result == DATA

    async with trio.open_nursery() as nursery:
        nursery.start_soon(writer)
        nursery.start_soon(reader)


@pytest.mark.trio
async def test_mplex_stream_deadline_validation_negative_ttl(mplex_stream_pair):
    """Test that deadline methods return False for negative TTL values."""
    stream_0, stream_1 = mplex_stream_pair

    # Test set_deadline with negative TTL
    assert stream_0.set_deadline(-1) is False
    assert stream_0.set_deadline(-10) is False
    # Deadlines should remain unchanged
    assert stream_0.read_deadline is None
    assert stream_0.write_deadline is None

    # Test set_read_deadline with negative TTL
    assert stream_0.set_read_deadline(-1) is False
    assert stream_0.set_read_deadline(-5) is False
    # Read deadline should remain unchanged
    assert stream_0.read_deadline is None

    # Test set_write_deadline with negative TTL
    assert stream_0.set_write_deadline(-1) is False
    assert stream_0.set_write_deadline(-3) is False
    # Write deadline should remain unchanged
    assert stream_0.write_deadline is None


@pytest.mark.trio
async def test_mplex_stream_deadline_validation_zero_ttl(mplex_stream_pair):
    """Test that deadline methods accept zero TTL values."""
    stream_0, stream_1 = mplex_stream_pair

    # Test set_deadline with zero TTL (should be valid)
    assert stream_0.set_deadline(0) is True
    assert stream_0.read_deadline == 0
    assert stream_0.write_deadline == 0

    # Test set_read_deadline with zero TTL
    assert stream_0.set_read_deadline(0) is True
    assert stream_0.read_deadline == 0

    # Test set_write_deadline with zero TTL
    assert stream_0.set_write_deadline(0) is True
    assert stream_0.write_deadline == 0


@pytest.mark.trio
async def test_mplex_stream_deadline_validation_positive_ttl(mplex_stream_pair):
    """Test that deadline methods accept positive TTL values."""
    stream_0, stream_1 = mplex_stream_pair

    # Test set_deadline with positive TTL
    assert stream_0.set_deadline(1) is True
    assert stream_0.read_deadline == 1
    assert stream_0.write_deadline == 1

    # Test set_read_deadline with positive TTL
    assert stream_0.set_read_deadline(5) is True
    assert stream_0.read_deadline == 5

    # Test set_write_deadline with positive TTL
    assert stream_0.set_write_deadline(10) is True
    assert stream_0.write_deadline == 10

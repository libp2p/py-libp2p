import pytest
from unittest.mock import AsyncMock
import trio
from trio.testing import (
    wait_all_tasks_blocked,
)

from libp2p.stream_muxer.mplex.exceptions import (
    MplexStreamClosed,
    MplexStreamEOF,
    MplexStreamReset,
)
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_MESSAGE_CHANNEL_SIZE,
    HeaderTags,
    StreamID,
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
    await trio.sleep(0.01)
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
async def test_send_message_return_type(mplex_conn_pair):
    """
    Tests that send_message returns an integer representing the bytes written.
    """
    mplex_conn = mplex_conn_pair[0]

    # Mock the underlying connection's write method
    mplex_conn.secured_conn.write = AsyncMock()

    # Define some dummy data
    dummy_data = b"hello"
    # Header: 1 byte for stream ID 0, flag 0. Varint prefix for data: 1 byte for len 5.
    expected_len = 1 + 1 + len(dummy_data)

    # Call the function
    bytes_written = await mplex_conn.send_message(
        flag=HeaderTags.MessageInitiator,
        data=dummy_data,
        stream_id=StreamID(channel_id=0, is_initiator=True)
    )

    # Assert the type and a reasonable value
    assert isinstance(bytes_written, int)
    assert bytes_written == expected_len


@pytest.mark.trio
async def test_handle_incoming_logs_unknown_flag(mplex_conn_pair, capsys):
    """
    Tests that an unknown message flag is logged correctly.
    """
    mplex_conn = mplex_conn_pair[0]

    # Mock the read_message to return an unknown flag (e.g., 99)
    mplex_conn.read_message = AsyncMock(return_value=(0, 99, b"data"))

    await mplex_conn._handle_incoming_message()

    # ASSERT ON STDERR: Use capsys to read from the standard error stream.
    captured = capsys.readouterr()
    assert "Received message with unknown flag 99" in captured.err


@pytest.mark.trio
async def test_handle_message_logs_unknown_stream(mplex_conn_pair, capsys):
    """
    Tests that a message for an unknown stream is logged.
    """
    mplex_conn = mplex_conn_pair[0]

    unknown_stream_id = StreamID(channel_id=123, is_initiator=True)

    # Call directly, ensuring the stream ID is not in mplex_conn.streams
    await mplex_conn._handle_message(unknown_stream_id, b"some data")

    # ASSERT ON STDERR: Use capsys to read from the standard error stream.
    captured = capsys.readouterr()
    assert f"Received message for unknown stream {unknown_stream_id}" in captured.err


@pytest.mark.trio
async def test_handle_message_logs_data_after_close(mplex_conn_pair, capsys):
    """
    Tests that data received after a remote close is logged.
    This test is refactored to be a direct unit test to avoid race conditions.
    """
    # 1. Use one connection for a controlled test environment.
    mplex_conn = mplex_conn_pair[0]

    # 2. Manually create a stream and add it to the connection.
    stream_id = StreamID(channel_id=99, is_initiator=True)
    stream = await mplex_conn._initialize_stream(stream_id, "test_stream_for_close")

    # 3. Manually set the stream's state to "remote closed".
    #    This simulates the event that the test wants to check for.
    async with stream.close_lock:
        stream.event_remote_closed.set()

    # 4. Directly call the function to test its logic against the prepared state.
    await mplex_conn._handle_message(stream.stream_id, b"late data")

    # 5. ASSERT ON STDERR: Use capsys to read from the standard error stream.
    captured = capsys.readouterr()
    assert "Received data from remote after stream was closed by them" in captured.err
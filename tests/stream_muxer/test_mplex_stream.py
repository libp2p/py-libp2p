import pytest
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

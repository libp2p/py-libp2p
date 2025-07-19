from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trio
from trio.testing import wait_all_tasks_blocked

from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
)
from libp2p.stream_muxer.mplex.constants import HeaderTags
from libp2p.stream_muxer.mplex.datastructures import StreamID
from libp2p.stream_muxer.mplex.exceptions import (
    MplexStreamClosed,
    MplexStreamEOF,
    MplexStreamReset,
)
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream


class MockMuxedConn:
    """A mock Mplex connection for testing purposes."""

    def __init__(self):
        self.sent_messages = []
        self.streams: dict[StreamID, MplexStream] = {}
        self.streams_lock = trio.Lock()
        self.is_unavailable = False

    async def send_message(
        self, flag: HeaderTags, data: bytes | None, stream_id: StreamID
    ) -> None:
        """Mocks sending a message over the connection."""
        if self.is_unavailable:
            raise MuxedConnUnavailable("Connection is unavailable")
        self.sent_messages.append((flag, data, stream_id))
        # Yield to allow other tasks to run
        await trio.lowlevel.checkpoint()

    def get_remote_address(self) -> tuple[str, int]:
        """Mocks getting the remote address."""
        return "127.0.0.1", 4001


@pytest.fixture
async def mplex_stream():
    """Provides a fully initialized MplexStream and its communication channels."""
    # Use a buffered channel to prevent deadlocks in simple tests
    send_chan, recv_chan = trio.open_memory_channel(10)
    stream_id = StreamID(1, is_initiator=True)
    muxed_conn = MockMuxedConn()
    stream = MplexStream("test-stream", stream_id, cast(Any, muxed_conn), recv_chan)
    muxed_conn.streams[stream_id] = stream

    yield stream, send_chan, muxed_conn

    # Cleanup: Close channels and reset stream state
    await send_chan.aclose()
    await recv_chan.aclose()
    # Reset stream state to prevent cross-test contamination
    stream.event_local_closed = trio.Event()
    stream.event_remote_closed = trio.Event()
    stream.event_reset = trio.Event()


# ===============================================
# 1. Tests for Stream-Level Lock Integration
# ===============================================


@pytest.mark.trio
async def test_stream_write_is_protected_by_rwlock(mplex_stream):
    """Verify that stream.write() acquires and releases the write lock."""
    stream, _, muxed_conn = mplex_stream

    # Mock lock methods
    original_acquire = stream.rw_lock.acquire_write
    original_release = stream.rw_lock.release_write

    stream.rw_lock.acquire_write = AsyncMock(wraps=original_acquire)
    stream.rw_lock.release_write = MagicMock(wraps=original_release)

    await stream.write(b"test data")

    stream.rw_lock.acquire_write.assert_awaited_once()
    stream.rw_lock.release_write.assert_called_once()

    # Verify the message was actually sent
    assert len(muxed_conn.sent_messages) == 1
    flag, data, stream_id = muxed_conn.sent_messages[0]
    assert flag == HeaderTags.MessageInitiator
    assert data == b"test data"
    assert stream_id == stream.stream_id


@pytest.mark.trio
async def test_stream_read_is_protected_by_rwlock(mplex_stream):
    """Verify that stream.read() acquires and releases the read lock."""
    stream, send_chan, _ = mplex_stream

    # Mock lock methods
    original_acquire = stream.rw_lock.acquire_read
    original_release = stream.rw_lock.release_read

    stream.rw_lock.acquire_read = AsyncMock(wraps=original_acquire)
    stream.rw_lock.release_read = AsyncMock(wraps=original_release)

    await send_chan.send(b"hello")
    result = await stream.read(5)

    stream.rw_lock.acquire_read.assert_awaited_once()
    stream.rw_lock.release_read.assert_awaited_once()
    assert result == b"hello"


@pytest.mark.trio
async def test_multiple_readers_can_coexist(mplex_stream):
    """Verify multiple readers can operate concurrently."""
    stream, send_chan, _ = mplex_stream

    # Send enough data for both reads
    await send_chan.send(b"data1")
    await send_chan.send(b"data2")

    # Track lock acquisition order
    acquisition_order = []
    release_order = []

    # Patch lock methods to track concurrency
    original_acquire = stream.rw_lock.acquire_read
    original_release = stream.rw_lock.release_read

    async def tracked_acquire():
        nonlocal acquisition_order
        acquisition_order.append("start")
        await original_acquire()
        acquisition_order.append("acquired")

    async def tracked_release():
        nonlocal release_order
        release_order.append("start")
        await original_release()
        release_order.append("released")

    with (
        patch.object(
            stream.rw_lock, "acquire_read", side_effect=tracked_acquire, autospec=True
        ),
        patch.object(
            stream.rw_lock, "release_read", side_effect=tracked_release, autospec=True
        ),
    ):
        # Execute concurrent reads
        async with trio.open_nursery() as nursery:
            nursery.start_soon(stream.read, 5)
            nursery.start_soon(stream.read, 5)

    # Verify both reads happened
    assert acquisition_order.count("start") == 2
    assert acquisition_order.count("acquired") == 2
    assert release_order.count("start") == 2
    assert release_order.count("released") == 2


@pytest.mark.trio
async def test_writer_blocks_readers(mplex_stream):
    """Verify that a writer blocks all readers and new readers queue behind."""
    stream, send_chan, _ = mplex_stream

    writer_acquired = trio.Event()
    readers_ready = trio.Event()
    writer_finished = trio.Event()
    all_readers_started = trio.Event()
    all_readers_done = trio.Event()

    counters = {"reader_start_count": 0, "reader_done_count": 0}
    reader_target = 3
    reader_start_lock = trio.Lock()

    # Patch write lock to control test flow
    original_acquire_write = stream.rw_lock.acquire_write
    original_release_write = stream.rw_lock.release_write

    async def tracked_acquire_write():
        await original_acquire_write()
        writer_acquired.set()
        # Wait for readers to queue up
        await readers_ready.wait()

    # Must be synchronous since real release_write is sync
    def tracked_release_write():
        original_release_write()
        writer_finished.set()

    with (
        patch.object(
            stream.rw_lock, "acquire_write", side_effect=tracked_acquire_write
        ),
        patch.object(
            stream.rw_lock, "release_write", side_effect=tracked_release_write
        ),
    ):
        async with trio.open_nursery() as nursery:
            # Start writer
            nursery.start_soon(stream.write, b"test")
            await writer_acquired.wait()

            # Start readers
            async def reader_task():
                async with reader_start_lock:
                    counters["reader_start_count"] += 1
                    if counters["reader_start_count"] == reader_target:
                        all_readers_started.set()

                try:
                    # This will block until data is available
                    await stream.read(5)
                except (MplexStreamReset, MplexStreamEOF):
                    pass
                finally:
                    async with reader_start_lock:
                        counters["reader_done_count"] += 1
                        if counters["reader_done_count"] == reader_target:
                            all_readers_done.set()

            for _ in range(reader_target):
                nursery.start_soon(reader_task)

            # Wait until all readers are started
            await all_readers_started.wait()

            # Let the writer finish and release the lock
            readers_ready.set()
            await writer_finished.wait()

            # Send data to unblock the readers
            for i in range(reader_target):
                await send_chan.send(b"data" + str(i).encode())

            # Wait for all readers to finish
            await all_readers_done.wait()


@pytest.mark.trio
async def test_writer_waits_for_readers(mplex_stream):
    """Verify a writer waits for existing readers to complete."""
    stream, send_chan, _ = mplex_stream
    readers_started = trio.Event()
    writer_entered = trio.Event()
    writer_acquiring = trio.Event()
    readers_finished = trio.Event()

    # Send data for readers
    await send_chan.send(b"data1")
    await send_chan.send(b"data2")

    # Patch read lock to control test flow
    original_acquire_read = stream.rw_lock.acquire_read

    async def tracked_acquire_read():
        await original_acquire_read()
        readers_started.set()
        # Wait until readers are allowed to finish
        await readers_finished.wait()

    # Patch write lock to detect when writer is blocked
    original_acquire_write = stream.rw_lock.acquire_write

    async def tracked_acquire_write():
        writer_acquiring.set()
        await original_acquire_write()
        writer_entered.set()

    with (
        patch.object(stream.rw_lock, "acquire_read", side_effect=tracked_acquire_read),
        patch.object(
            stream.rw_lock, "acquire_write", side_effect=tracked_acquire_write
        ),
    ):
        async with trio.open_nursery() as nursery:
            # Start readers
            nursery.start_soon(stream.read, 5)
            nursery.start_soon(stream.read, 5)

            # Wait for at least one reader to acquire the lock
            await readers_started.wait()

            # Start writer (should block)
            nursery.start_soon(stream.write, b"test")

            # Wait for writer to start acquiring lock
            await writer_acquiring.wait()

            # Verify writer hasn't entered critical section
            assert not writer_entered.is_set()

            # Allow readers to finish
            readers_finished.set()

            # Verify writer can proceed
            await writer_entered.wait()


@pytest.mark.trio
async def test_lock_behavior_during_cancellation(mplex_stream):
    """Verify that a lock is released when a task holding it is cancelled."""
    stream, _, _ = mplex_stream

    reader_acquired_lock = trio.Event()

    async def cancellable_reader(task_status):
        async with stream.rw_lock.read_lock():
            reader_acquired_lock.set()
            task_status.started()
            # Wait indefinitely until cancelled.
            await trio.sleep_forever()

    async with trio.open_nursery() as nursery:
        # Start the reader and wait for it to acquire the lock.
        await nursery.start(cancellable_reader)
        await reader_acquired_lock.wait()

        # Now that the reader has the lock, cancel the nursery.
        # This will cancel the reader task, and its lock should be released.
        nursery.cancel_scope.cancel()

    # After the nursery is cancelled, the reader should have released the lock.
    # To verify, we try to acquire a write lock. If the read lock was not
    # released, this will time out.
    with trio.move_on_after(1) as cancel_scope:
        async with stream.rw_lock.write_lock():
            pass
    if cancel_scope.cancelled_caught:
        pytest.fail(
            "Write lock could not be acquired after a cancelled reader, "
            "indicating the read lock was not released."
        )


@pytest.mark.trio
async def test_concurrent_read_write_sequence(mplex_stream):
    """Verify complex sequence of interleaved reads and writes."""
    stream, send_chan, _ = mplex_stream
    results = []
    # Use a mock to intercept writes and feed them back to the read channel
    original_write = stream.write

    reader1_finished = trio.Event()
    writer1_finished = trio.Event()
    reader2_finished = trio.Event()

    async def mocked_write(data: bytes) -> None:
        await original_write(data)
        # Simulate the other side receiving the data and sending a response
        # by putting data into the read channel.
        await send_chan.send(data)

    with patch.object(stream, "write", wraps=mocked_write) as patched_write:
        async with trio.open_nursery() as nursery:
            # Test scenario:
            # 1. Reader 1 starts, waits for data.
            # 2. Writer 1 writes, which gets fed back to the stream.
            # 3. Reader 2 starts, reads what Writer 1 wrote.
            # 4. Writer 2 writes.

            async def reader1():
                nonlocal results
                results.append("R1 start")
                data = await stream.read(5)
                results.append(data)
                results.append("R1 done")
                reader1_finished.set()

            async def writer1():
                nonlocal results
                await reader1_finished.wait()
                results.append("W1 start")
                await stream.write(b"write1")
                results.append("W1 done")
                writer1_finished.set()

            async def reader2():
                nonlocal results
                await writer1_finished.wait()
                # This will read the data from writer1
                results.append("R2 start")
                data = await stream.read(6)
                results.append(data)
                results.append("R2 done")
                reader2_finished.set()

            async def writer2():
                nonlocal results
                await reader2_finished.wait()
                results.append("W2 start")
                await stream.write(b"write2")
                results.append("W2 done")

            # Execute sequence
            nursery.start_soon(reader1)
            nursery.start_soon(writer1)
            nursery.start_soon(reader2)
            nursery.start_soon(writer2)

            await send_chan.send(b"data1")

    # Verify sequence and that write was called
    assert patched_write.call_count == 2
    assert results == [
        "R1 start",
        b"data1",
        "R1 done",
        "W1 start",
        "W1 done",
        "R2 start",
        b"write1",
        "R2 done",
        "W2 start",
        "W2 done",
    ]


# ===============================================
# 2. Tests for Reset, EOF, and Close Interactions
# ===============================================


@pytest.mark.trio
async def test_read_after_remote_close_triggers_eof(mplex_stream):
    """Verify reading from a remotely closed stream returns EOF correctly."""
    stream, send_chan, _ = mplex_stream

    # Send some data that can be read first
    await send_chan.send(b"data")
    # Close the channel to signify no more data will ever arrive
    await send_chan.aclose()

    # Mark the stream as remotely closed
    stream.event_remote_closed.set()

    # The first read should succeed, consuming the buffered data
    data = await stream.read(4)
    assert data == b"data"

    # Now that the buffer is empty and the channel is closed, this should raise EOF
    with pytest.raises(MplexStreamEOF):
        await stream.read(1)


@pytest.mark.trio
async def test_read_on_closed_stream_raises_eof(mplex_stream):
    """Test that reading from a closed stream with no data raises EOF."""
    stream, send_chan, _ = mplex_stream
    stream.event_remote_closed.set()
    await send_chan.aclose()  # Ensure the channel is closed

    # Reading from a stream that is closed and has no data should raise EOF
    with pytest.raises(MplexStreamEOF):
        await stream.read(100)


@pytest.mark.trio
async def test_write_to_locally_closed_stream_raises(mplex_stream):
    """Verify writing to a locally closed stream raises MplexStreamClosed."""
    stream, _, _ = mplex_stream
    stream.event_local_closed.set()

    with pytest.raises(MplexStreamClosed):
        await stream.write(b"this should fail")


@pytest.mark.trio
async def test_read_from_reset_stream_raises(mplex_stream):
    """Verify reading from a reset stream raises MplexStreamReset."""
    stream, _, _ = mplex_stream
    stream.event_reset.set()

    with pytest.raises(MplexStreamReset):
        await stream.read(10)


@pytest.mark.trio
async def test_write_to_reset_stream_raises(mplex_stream):
    """Verify writing to a reset stream raises MplexStreamClosed."""
    stream, _, _ = mplex_stream
    # A stream reset implies it's also locally closed.
    await stream.reset()

    # The `write` method checks `event_local_closed`, which `reset` sets.
    with pytest.raises(MplexStreamClosed):
        await stream.write(b"this should also fail")


@pytest.mark.trio
async def test_stream_reset_cleans_up_resources(mplex_stream):
    """Verify reset() cleans up stream state and resources."""
    stream, _, muxed_conn = mplex_stream
    stream_id = stream.stream_id

    assert stream_id in muxed_conn.streams
    await stream.reset()

    assert stream.event_reset.is_set()
    assert stream.event_local_closed.is_set()
    assert stream.event_remote_closed.is_set()
    assert (HeaderTags.ResetInitiator, None, stream_id) in muxed_conn.sent_messages
    assert stream_id not in muxed_conn.streams
    # Verify the underlying data channel is closed
    with pytest.raises(trio.ClosedResourceError):
        await stream.incoming_data_channel.receive()


# ===============================================
# 3. Rigorous Concurrency Tests with Events
# ===============================================


@pytest.mark.trio
async def test_writer_is_blocked_by_reader_using_events(mplex_stream):
    """Verify a writer must wait for a reader using trio.Event for synchronization."""
    stream, _, _ = mplex_stream

    reader_has_lock = trio.Event()
    writer_finished = trio.Event()

    async def reader():
        async with stream.rw_lock.read_lock():
            reader_has_lock.set()
            # Hold the lock until the writer has finished its attempt
            await writer_finished.wait()

    async def writer():
        await reader_has_lock.wait()
        # This call will now block until the reader releases the lock
        await stream.write(b"data")
        writer_finished.set()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(reader)
        nursery.start_soon(writer)

        # Verify writer is blocked
        await wait_all_tasks_blocked()
        assert not writer_finished.is_set()

        # Signal the reader to finish
        writer_finished.set()


@pytest.mark.trio
async def test_multiple_readers_can_read_concurrently_using_events(mplex_stream):
    """Verify that multiple readers can acquire a read lock simultaneously."""
    stream, _, _ = mplex_stream

    counters = {"readers_in_critical_section": 0}
    lock = trio.Lock()  # To safely mutate the counter

    reader1_acquired = trio.Event()
    reader2_acquired = trio.Event()
    all_readers_finished = trio.Event()

    async def concurrent_reader(event_to_set: trio.Event):
        async with stream.rw_lock.read_lock():
            async with lock:
                counters["readers_in_critical_section"] += 1
            event_to_set.set()
            # Wait until all readers have finished before exiting the lock context
            await all_readers_finished.wait()
            async with lock:
                counters["readers_in_critical_section"] -= 1

    async with trio.open_nursery() as nursery:
        nursery.start_soon(concurrent_reader, reader1_acquired)
        nursery.start_soon(concurrent_reader, reader2_acquired)

        # Wait for both readers to acquire their locks
        await reader1_acquired.wait()
        await reader2_acquired.wait()

        # Check that both were in the critical section at the same time
        async with lock:
            assert counters["readers_in_critical_section"] == 2

        # Signal for all readers to finish
        all_readers_finished.set()

        # Verify they exit cleanly
        await wait_all_tasks_blocked()
        async with lock:
            assert counters["readers_in_critical_section"] == 0

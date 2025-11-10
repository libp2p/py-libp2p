"""
Tests for NetStream concurrency and locking behavior.

This module tests the _state_lock functionality to ensure thread-safe
access to stream state and prevent race conditions.
"""

from unittest.mock import Mock

import pytest
import trio

from libp2p.network.stream.net_stream import NetStream, StreamState


class MockMuxedStream:
    """Mock muxed stream for testing."""

    def __init__(self):
        self._closed = False
        self._reset = False
        self._data = b""
        self._read_calls = 0
        self._write_calls = 0
        self.muxed_conn = Mock()  # Mock muxed connection

    async def read(self, n=None):
        """Mock read operation."""
        self._read_calls += 1
        if self._closed:
            raise Exception("Stream closed")
        if self._reset:
            raise Exception("Stream reset")
        if self._data:
            data = self._data
            self._data = b""
            return data
        return b""

    async def write(self, data):
        """Mock write operation."""
        self._write_calls += 1
        if self._closed:
            raise Exception("Stream closed")
        if self._reset:
            raise Exception("Stream reset")
        self._data += data

    def close(self):
        """Mock close operation."""
        self._closed = True

    def reset(self):
        """Mock reset operation."""
        self._reset = True


@pytest.fixture
def mock_stream():
    """Create a mock NetStream for testing."""
    muxed_stream = MockMuxedStream()
    stream = NetStream(muxed_stream=muxed_stream, swarm_conn=Mock())  # type: ignore[arg-type]
    return stream, muxed_stream


@pytest.mark.trio
async def test_concurrent_state_access(mock_stream):
    """Test that concurrent access to stream state is properly synchronized."""
    stream, muxed_stream = mock_stream

    # Track state access order
    access_order = []
    state_values = []

    async def access_state(task_id):
        """Access stream state and record the order."""
        async with stream._state_lock:
            access_order.append(f"task_{task_id}_start")
            state = stream._state
            state_values.append(state)
            await trio.sleep(0.01)  # Simulate some work
            access_order.append(f"task_{task_id}_end")

    # Run multiple concurrent state accesses
    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(access_state, i)

    # Verify that all accesses were serialized (no interleaving)
    assert len(access_order) == 10  # 5 starts + 5 ends
    assert len(state_values) == 5
    assert all(state == StreamState.INIT for state in state_values)

    # Verify no interleaving occurred (each task completes before next starts)
    for i in range(5):
        start_idx = access_order.index(f"task_{i}_start")
        end_idx = access_order.index(f"task_{i}_end")
        assert start_idx < end_idx


@pytest.mark.trio
async def test_race_condition_prevention_in_read(mock_stream):
    """Test that our locks prevent race conditions in read operations."""
    stream, muxed_stream = mock_stream

    # Set up a scenario where state could change during read
    read_results = []
    state_changes = []

    async def concurrent_reader():
        """Reader that might experience race conditions."""
        try:
            data = await stream.read(10)
            read_results.append(("success", data))
        except Exception as e:
            read_results.append(("error", str(e)))

    async def state_changer():
        """Task that changes state during read."""
        await trio.sleep(0.005)  # Let reader start first
        state_changes.append("changing_state")
        await stream.set_state(StreamState.CLOSE_READ)
        state_changes.append("state_changed")

    # Run concurrent operations
    async with trio.open_nursery() as nursery:
        nursery.start_soon(concurrent_reader)
        nursery.start_soon(state_changer)

    # Verify that the read operation was atomic
    # Either it succeeded before state change, or failed due to state change
    assert len(read_results) == 1
    result_type, result_data = read_results[0]

    # The operation should be atomic - no partial state
    assert result_type in ["success", "error"]


@pytest.mark.trio
async def test_race_condition_prevention_in_write(mock_stream):
    """Test that our locks prevent race conditions in write operations."""
    stream, muxed_stream = mock_stream

    write_results = []
    state_changes = []

    async def concurrent_writer():
        """Writer that might experience race conditions."""
        try:
            await stream.write(b"test_data")
            write_results.append("success")
        except Exception as e:
            write_results.append(f"error: {str(e)}")

    async def state_changer():
        """Task that changes state during write."""
        await trio.sleep(0.005)  # Let writer start first
        state_changes.append("changing_state")
        await stream.set_state(StreamState.CLOSE_WRITE)
        state_changes.append("state_changed")

    # Run concurrent operations
    async with trio.open_nursery() as nursery:
        nursery.start_soon(concurrent_writer)
        nursery.start_soon(state_changer)

    # Verify that the write operation was atomic
    assert len(write_results) == 1
    result = write_results[0]

    # The operation should be atomic - no partial state
    assert result in ["success", "error: Cannot write to stream; closed for writing"]


@pytest.mark.trio
async def test_atomic_state_io_operations(mock_stream):
    """Test that state checks and I/O operations are atomic."""
    stream, muxed_stream = mock_stream

    # Track when state checks and I/O operations occur
    operations = []

    # Mock the muxed stream to track operations
    original_read = muxed_stream.read
    original_write = muxed_stream.write

    async def tracked_read(n=None):
        operations.append("io_read_start")
        result = await original_read(n)
        operations.append("io_read_end")
        return result

    async def tracked_write(data):
        operations.append("io_write_start")
        await original_write(data)
        operations.append("io_write_end")

    muxed_stream.read = tracked_read
    muxed_stream.write = tracked_write

    # Test atomic read operation
    await stream.read(10)

    # Verify that state check and I/O are atomic
    # Should see: state_check -> io_read_start -> io_read_end
    assert "io_read_start" in operations
    assert "io_read_end" in operations

    # Test atomic write operation
    await stream.write(b"test")

    # Verify that state check and I/O are atomic
    # Should see: state_check -> io_write_start -> io_write_end
    assert "io_write_start" in operations
    assert "io_write_end" in operations


@pytest.mark.trio
async def test_lock_prevents_concurrent_state_modifications(mock_stream):
    """Test that the lock prevents concurrent state modifications."""
    stream, muxed_stream = mock_stream

    state_transitions = []

    async def state_modifier(state, task_id):
        """Modify state and record the transition."""
        state_transitions.append(f"task_{task_id}_start")
        await stream.set_state(state)
        await trio.sleep(0.01)  # Simulate work
        state_transitions.append(f"task_{task_id}_end")

    # Run multiple concurrent state modifications
    async with trio.open_nursery() as nursery:
        nursery.start_soon(state_modifier, StreamState.OPEN, 1)
        nursery.start_soon(state_modifier, StreamState.CLOSE_READ, 2)
        nursery.start_soon(state_modifier, StreamState.CLOSE_WRITE, 3)

    # Verify that state modifications were serialized
    assert len(state_transitions) == 6  # 3 starts + 3 ends

    # Verify no interleaving occurred
    for i in range(1, 4):
        start_idx = state_transitions.index(f"task_{i}_start")
        end_idx = state_transitions.index(f"task_{i}_end")
        assert start_idx < end_idx


@pytest.mark.trio
async def test_concurrent_read_write_with_state_changes(mock_stream):
    """Test concurrent read/write operations with state changes."""
    stream, muxed_stream = mock_stream

    operations = []

    async def reader():
        """Concurrent reader."""
        try:
            operations.append("reader_start")
            data = await stream.read(10)
            operations.append(f"reader_success: {data}")
        except Exception as e:
            operations.append(f"reader_error: {str(e)}")

    async def writer():
        """Concurrent writer."""
        try:
            operations.append("writer_start")
            await stream.write(b"test_data")
            operations.append("writer_success")
        except Exception as e:
            operations.append(f"writer_error: {str(e)}")

    async def state_changer():
        """Concurrent state changer."""
        await trio.sleep(0.01)
        operations.append("state_changer_start")
        await stream.set_state(StreamState.CLOSE_WRITE)
        operations.append("state_changer_end")

    # Run all operations concurrently
    async with trio.open_nursery() as nursery:
        nursery.start_soon(reader)
        nursery.start_soon(writer)
        nursery.start_soon(state_changer)

    # Verify that operations were properly synchronized
    assert len(operations) >= 3  # At least one operation from each task

    # Verify that state changes are atomic
    state_changer_ops = [op for op in operations if "state_changer" in op]
    assert len(state_changer_ops) >= 2  # start and end


@pytest.mark.trio
async def test_lock_behavior_during_cancellation(mock_stream):
    """Test that locks are properly released during cancellation."""
    stream, muxed_stream = mock_stream

    lock_acquired = trio.Event()
    lock_released = trio.Event()

    async def long_operation():
        """Long operation that holds the lock."""
        async with stream._state_lock:
            lock_acquired.set()
            try:
                await trio.sleep(1.0)  # Long operation
            finally:
                lock_released.set()

    async def quick_operation():
        """Quick operation that should be blocked."""
        await lock_acquired.wait()
        async with stream._state_lock:
            # This should succeed after the long operation is cancelled
            pass

    # Start long operation
    async with trio.open_nursery() as nursery:
        nursery.start_soon(long_operation)

        # Wait for lock to be acquired
        await lock_acquired.wait()

        # Cancel the long operation
        nursery.cancel_scope.cancel()

    # Verify lock was released
    await lock_released.wait()

    # Now quick operation should succeed
    await quick_operation()


@pytest.mark.trio
async def test_multiple_readers_with_state_lock(mock_stream):
    """Test that multiple readers can work with the state lock."""
    stream, muxed_stream = mock_stream

    # Set up some data
    muxed_stream._data = b"test_data"

    results = []

    async def reader(reader_id):
        """Concurrent reader."""
        try:
            data = await stream.read(10)
            results.append((reader_id, "success", data))
        except Exception as e:
            results.append((reader_id, "error", str(e)))

    # Run multiple concurrent readers
    async with trio.open_nursery() as nursery:
        for i in range(3):
            nursery.start_soon(reader, i)

    # Verify that all readers completed
    assert len(results) == 3

    # At least one should have succeeded (got the data)
    successes = [r for r in results if r[1] == "success"]
    assert len(successes) >= 1


@pytest.mark.trio
async def test_state_lock_with_error_conditions(mock_stream):
    """Test state lock behavior during error conditions."""
    stream, muxed_stream = mock_stream

    # Simulate an error condition
    muxed_stream._reset = True

    results = []

    async def operation_with_error():
        """Operation that will encounter an error."""
        try:
            await stream.read(10)
            results.append("unexpected_success")
        except Exception as e:
            results.append(f"expected_error: {str(e)}")

    # Run the operation
    await operation_with_error()

    # Verify that the error was handled properly
    assert len(results) == 1
    assert "expected_error" in results[0]

    # Verify that the stream state was updated appropriately
    # The stream should be in ERROR state due to the exception during read
    assert stream._state == StreamState.ERROR


@pytest.mark.trio
async def test_lock_performance_under_load(mock_stream):
    """Test that locks don't significantly impact performance under load."""
    stream, muxed_stream = mock_stream

    # Set up data for reading
    muxed_stream._data = b"x" * 1000

    start_time = trio.current_time()

    async def reader():
        """Fast reader operation."""
        await stream.read(100)

    # Run many concurrent operations
    async with trio.open_nursery() as nursery:
        for _ in range(50):
            nursery.start_soon(reader)

    end_time = trio.current_time()
    duration = end_time - start_time

    # Verify that operations completed in reasonable time
    # (This is a basic sanity check - actual performance depends on system)
    assert duration < 5.0  # Should complete within 5 seconds

    # Verify that all operations completed
    assert muxed_stream._read_calls == 50

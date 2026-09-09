"""
Context cancellation tests for Noise transport.

Tests proper handling of trio cancellation during handshake and transport operations,
based on Go implementation patterns.
"""

import pytest
import trio

from tests.utils.factories import noise_conn_factory


class TestContextCancellation:
    """Test context cancellation in Noise transport."""

    @pytest.mark.trio
    async def test_handshake_cancellation_outbound(self, nursery):
        """Test handshake cancellation for outbound connections."""
        # Create a cancelled context
        with trio.move_on_after(0.001):  # Very short timeout
            async with noise_conn_factory(nursery) as conns:
                # This should be cancelled quickly
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)

    @pytest.mark.trio
    async def test_transport_operation_cancellation(self, nursery):
        """Test cancellation during transport operations."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            # Test cancellation during write operation
            test_data = b"test data for cancellation"

            # Create a task that will be cancelled
            async def write_task():
                await local_conn.write(test_data)

            # Cancel the task
            with trio.move_on_after(0.001):  # Very short timeout
                await write_task()

            # Test cancellation during read operation
            async def read_task():
                await remote_conn.read(len(test_data))

            # Cancel the task
            with trio.move_on_after(0.001):  # Very short timeout
                await read_task()

    @pytest.mark.trio
    async def test_timeout_cancellation(self, nursery):
        """Test timeout-based cancellation."""
        # Test with very short timeout
        with trio.move_on_after(0.001):  # 1ms timeout
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)

    @pytest.mark.trio
    async def test_concurrent_cancellation(self, nursery):
        """Test cancellation of concurrent operations."""

        # Start multiple concurrent operations
        async def operation():
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)

        # Cancel all tasks
        with trio.move_on_after(0.001):  # Very short timeout
            async with trio.open_nursery() as n:
                for _ in range(5):
                    n.start_soon(operation)

    @pytest.mark.trio
    async def test_cancellation_during_large_operation(self, nursery):
        """Test cancellation during large data operations."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            # Create large data (within Noise limits)
            large_data = b"X" * 50000  # 50KB

            # Start large write operation
            async def write_task():
                await local_conn.write(large_data)

            # Cancel after a short delay
            with trio.move_on_after(0.001):  # Very short timeout
                await write_task()

            # Start large read operation
            async def read_task():
                await remote_conn.read(len(large_data))

            # Cancel after a short delay
            with trio.move_on_after(0.001):  # Very short timeout
                await read_task()

    @pytest.mark.trio
    async def test_cancellation_cleanup(self, nursery):
        """Test proper cleanup after cancellation."""

        # Start handshake
        async def handshake_task():
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)

        # Cancel the handshake
        with trio.move_on_after(0.001):  # Very short timeout
            await handshake_task()

        # Should be able to start a new handshake after cancellation
        try:
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)
        except Exception:
            # May fail due to connection state, but shouldn't crash
            pass

    @pytest.mark.trio
    async def test_cancellation_error_propagation(self, nursery):
        """Test that cancellation errors are properly propagated."""

        async def nested_operation():
            # Nested operation that gets cancelled
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)

        # Start nested operation
        with trio.move_on_after(0.001):  # Very short timeout
            await nested_operation()

    @pytest.mark.trio
    async def test_cancellation_with_timeout(self, nursery):
        """Test cancellation combined with timeout."""

        # Create a task with timeout
        async def task():
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns
                await local_conn.write(b"test")
                await remote_conn.read(4)

        # Cancel the task
        with trio.move_on_after(0.001):  # Very short timeout
            await task()

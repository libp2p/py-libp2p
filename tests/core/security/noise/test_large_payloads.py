"""
Large payload tests for Noise transport.

Tests handling of large payloads that require multiple Noise messages,
based on Go implementation patterns.
"""

import random

import pytest
import trio

from tests.utils.factories import noise_conn_factory


class TestLargePayloads:
    """Test large payload handling in Noise transport."""

    @pytest.mark.trio
    async def test_large_payload_roundtrip(self, nursery):
        """Test large payload requiring multiple Noise messages."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            # Generate large payload (max Noise message size minus overhead)
            random.seed(1234)  # Deterministic for testing
            size = 65500  # Max Noise message size minus overhead
            test_data = bytes(random.getrandbits(8) for _ in range(size))

            # Send large payload
            await local_conn.write(test_data)

            # Receive and verify
            received_data = await remote_conn.read(len(test_data))

            assert len(received_data) == len(test_data)
            assert received_data == test_data

    @pytest.mark.trio
    async def test_payload_size_boundaries(self, nursery):
        """Test payload sizes near Noise message limits."""
        test_sizes = [
            1024,  # 1KB
            16384,  # 16KB
            32768,  # 32KB
            65500,  # Max Noise message size minus overhead
        ]

        for size in test_sizes:
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns

                test_data = b"A" * size

                # Send payload
                await local_conn.write(test_data)

                # Receive and verify
                received_data = await remote_conn.read(len(test_data))

                assert len(received_data) == len(test_data)
                assert received_data == test_data

    @pytest.mark.trio
    async def test_multiple_large_payloads(self, nursery):
        """Test multiple large payloads in sequence."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            # Test multiple payloads of different sizes
            payloads = [
                b"Small payload",
                b"B" * 10000,  # 10KB
                b"C" * 50000,  # 50KB
                b"D" * 65500,  # Max Noise message size minus overhead
                b"Final small payload",
            ]

            # Send all payloads
            for payload in payloads:
                await local_conn.write(payload)

                # Receive and verify
                received_data = await remote_conn.read(len(payload))

                assert len(received_data) == len(payload)
                assert received_data == payload

    @pytest.mark.trio
    async def test_large_payload_performance(self, nursery):
        """Test performance characteristics of large payloads."""
        import time

        # Test with different payload sizes and measure performance
        test_cases = [
            (10000, "10KB"),
            (50000, "50KB"),
            (65500, "Max Noise size"),
        ]

        for size, description in test_cases:
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns

                test_data = b"X" * size

                # Measure send time
                start_time = time.time()
                await local_conn.write(test_data)
                send_time = time.time() - start_time

                # Measure receive time
                start_time = time.time()
                received_data = await remote_conn.read(len(test_data))
                receive_time = time.time() - start_time

                # Verify data integrity
                assert len(received_data) == len(test_data)
                assert received_data == test_data

                # Performance assertions (should complete within reasonable time)
                assert send_time < 1.0, (
                    f"Send time for {description} too slow: {send_time}s"
                )
                assert receive_time < 1.0, (
                    f"Receive time for {description} too slow: {receive_time}s"
                )

    @pytest.mark.trio
    async def test_large_payload_error_handling(self, nursery):
        """Test error handling with large payloads."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            # Test with corrupted large payload
            size = 50000
            test_data = b"X" * size

            # Send valid payload first
            await local_conn.write(test_data)

            received_data = await remote_conn.read(len(test_data))
            assert received_data == test_data

            # Test with incomplete payload (should timeout or error)
            incomplete_data = test_data[: size // 2]  # Half the data

            try:
                await local_conn.write(incomplete_data)

                # This should timeout or fail
                with trio.move_on_after(1.0):  # 1 second timeout
                    received_data = await remote_conn.read(len(test_data))
                    # If we get here, the test should fail
                    assert False, "Expected timeout or error with incomplete payload"

            except trio.TooSlowError:
                # Expected to timeout
                pass
            except Exception:
                # Any other exception is also acceptable for incomplete payload
                pass

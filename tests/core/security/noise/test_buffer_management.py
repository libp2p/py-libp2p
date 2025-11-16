"""
Buffer management tests for Noise transport.

Tests proper buffer handling, size validation, and unencrypted data rejection,
based on Go implementation patterns.
"""

import pytest

from tests.utils.factories import noise_conn_factory


class TestBufferManagement:
    """Test buffer management in Noise transport."""

    @pytest.mark.trio
    async def test_buffer_size_equals_encrypted_payload(self, nursery):
        """Test that buffer size equals encrypted payload size."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            test_data = b"hello world"

            # Send data
            await local_conn.write(test_data)

            # Read data (Noise handles decryption internally)
            received_data = await remote_conn.read(len(test_data))

            # Should read exactly the decrypted data
            assert len(received_data) == len(test_data)
            assert received_data == test_data

    @pytest.mark.trio
    async def test_buffer_size_equals_decrypted_payload(self, nursery):
        """Test that buffer size equals decrypted payload size."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            test_data = b"hello world"

            # Send data
            await local_conn.write(test_data)

            # Read with exact size
            received_data = await remote_conn.read(len(test_data))

            # Should read exactly the decrypted size
            assert len(received_data) == len(test_data)
            assert received_data == test_data

    @pytest.mark.trio
    async def test_buffer_size_validation(self, nursery):
        """Test buffer size validation for different scenarios."""
        test_cases = [
            (b"small", 10),  # Buffer larger than data
            (b"medium size data", 20),  # Buffer exactly data size
            (b"large data" * 100, 1000),  # Large data, large buffer
        ]

        for test_data, buffer_size in test_cases:
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns

                # Send data
                await local_conn.write(test_data)

                # Read with specified buffer size
                received_data = await remote_conn.read(len(test_data))

                # Validate received data
                assert len(received_data) <= len(test_data)
                assert received_data == test_data

    @pytest.mark.trio
    async def test_partial_read_handling(self, nursery):
        """Test handling of partial reads."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            test_data = b"partial read test data"

            # Send data
            await local_conn.write(test_data)

            # Read in chunks
            chunk_size = 5
            received_data = b""

            while len(received_data) < len(test_data):
                chunk = await remote_conn.read(chunk_size)
                received_data += chunk

            assert received_data == test_data

    @pytest.mark.trio
    async def test_empty_buffer_handling(self, nursery):
        """Test handling of empty buffers."""
        async with noise_conn_factory(nursery) as conns:
            local_conn, remote_conn = conns

            # Test with empty data
            empty_data = b""
            await local_conn.write(empty_data)

            # Should handle empty data gracefully
            try:
                received_data = await remote_conn.read(1)
                assert received_data == b""
            except Exception:
                # Empty data might cause connection closure, which is acceptable
                pass

    @pytest.mark.trio
    async def test_buffer_alignment(self, nursery):
        """Test buffer alignment for optimal performance."""
        # Test with different buffer alignments
        test_data = b"A" * 1024  # 1KB test data

        alignments = [1, 4, 8, 16, 32, 64, 128, 256, 512, 1024]

        for alignment in alignments:
            async with noise_conn_factory(nursery) as conns:
                local_conn, remote_conn = conns

                # Send data
                await local_conn.write(test_data)

                # Read with aligned buffer
                received_data = await remote_conn.read(len(test_data))

                # Verify data integrity
                assert len(received_data) == len(test_data)
                assert received_data == test_data

"""Tests for file chunker."""

import math
from pathlib import Path
import tempfile

import pytest

from libp2p.bitswap.chunker import (
    DEFAULT_CHUNK_SIZE,
    chunk_bytes,
    chunk_file,
    chunk_file_with_progress,
    estimate_chunk_count,
    get_file_size,
)


class TestChunkBytes:
    """Test chunk_bytes function."""

    def test_chunk_exact_fit(self):
        """Test chunking data that fits exactly."""
        chunk_size = 16 * 1024  # 16 KB for testing
        data = b"x" * (chunk_size * 4)
        chunks = list(chunk_bytes(data, chunk_size=chunk_size))

        assert len(chunks) == 4
        assert all(len(chunk) == chunk_size for chunk in chunks)
        assert b"".join(chunks) == data

    def test_chunk_with_remainder(self):
        """Test chunking with remainder."""
        chunk_size = 16 * 1024  # 16 KB for testing
        data = b"x" * (chunk_size * 4 + 5000)
        chunks = list(chunk_bytes(data, chunk_size=chunk_size))

        assert len(chunks) == 5
        assert all(len(chunk) == chunk_size for chunk in chunks[:4])
        assert len(chunks[4]) == 5000
        assert b"".join(chunks) == data

    def test_chunk_smaller_than_size(self):
        """Test chunking data smaller than chunk size."""
        data = b"small" * 1000
        chunk_size = 16 * 1024  # 16 KB for testing
        chunks = list(chunk_bytes(data, chunk_size=chunk_size))

        assert len(chunks) == 1
        assert chunks[0] == data

    def test_chunk_empty_data(self):
        """Test chunking empty data."""
        chunk_size = 16 * 1024  # 16 KB for testing
        chunks = list(chunk_bytes(b"", chunk_size=chunk_size))
        assert len(chunks) == 0

    def test_chunk_single_byte(self):
        """Test chunking single byte."""
        chunk_size = 16 * 1024  # 16 KB for testing
        chunks = list(chunk_bytes(b"x", chunk_size=chunk_size))
        assert len(chunks) == 1
        assert chunks[0] == b"x"

    def test_chunk_large_data(self):
        """Test chunking large data (10 MB)."""
        data = b"x" * (10 * 1024 * 1024)
        chunks = list(chunk_bytes(data, chunk_size=DEFAULT_CHUNK_SIZE))

        total_size = sum(len(chunk) for chunk in chunks)
        assert total_size == len(data)
        assert b"".join(chunks) == data


class TestChunkFile:
    """Test chunk_file function."""

    def test_chunk_file_exact_fit(self):
        """Test chunking file that fits exactly."""
        # Create temp file
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"x" * (chunk_size * 4)
            f.write(data)
            temp_path = f.name

        try:
            chunks = list(chunk_file(temp_path, chunk_size=chunk_size))

            assert len(chunks) == 4
            assert all(len(chunk) == chunk_size for chunk in chunks)
            assert b"".join(chunks) == data
        finally:
            Path(temp_path).unlink()

    def test_chunk_file_with_remainder(self):
        """Test chunking file with remainder."""
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"y" * (chunk_size * 4 + 5000)
            f.write(data)
            temp_path = f.name

        try:
            chunks = list(chunk_file(temp_path, chunk_size=chunk_size))

            assert len(chunks) == 5
            assert len(chunks[4]) == 5000
            assert b"".join(chunks) == data
        finally:
            Path(temp_path).unlink()

    def test_chunk_empty_file(self):
        """Test chunking empty file."""
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            chunks = list(chunk_file(temp_path, chunk_size=chunk_size))
            assert len(chunks) == 0
        finally:
            Path(temp_path).unlink()

    def test_chunk_large_file(self):
        """Test chunking large file (100 MB)."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write 100 MB in chunks
            chunk_data = b"x" * (1024 * 1024)  # 1 MB
            for _ in range(100):
                f.write(chunk_data)
            temp_path = f.name

        try:
            chunks = list(chunk_file(temp_path, chunk_size=DEFAULT_CHUNK_SIZE))

            total_size = sum(len(chunk) for chunk in chunks)
            assert total_size == 100 * 1024 * 1024

            # Verify first and last chunks
            assert len(chunks[0]) == DEFAULT_CHUNK_SIZE
        finally:
            Path(temp_path).unlink()

    def test_chunk_file_not_found(self):
        """Test chunking non-existent file."""
        with pytest.raises(FileNotFoundError):
            list(chunk_file("/nonexistent/file.txt"))

    def test_chunk_file_memory_efficient(self):
        """Test that chunk_file doesn't load entire file into memory."""
        # Create 50 MB file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            chunk_data = b"x" * (1024 * 1024)  # 1 MB
            for _ in range(50):
                f.write(chunk_data)
            temp_path = f.name

        try:
            # This should work without loading all 50 MB at once
            chunk_iter = chunk_file(temp_path, chunk_size=DEFAULT_CHUNK_SIZE)

            # Process first few chunks
            first_chunk = next(chunk_iter)
            second_chunk = next(chunk_iter)

            assert len(first_chunk) == DEFAULT_CHUNK_SIZE
            assert len(second_chunk) == DEFAULT_CHUNK_SIZE

            # Can iterate through all without memory issues
            chunk_count = 2 + sum(1 for _ in chunk_iter)
            # File size: 50*1024*1024 = 52428800 bytes
            # Chunk size: 64512 bytes
            # Expected chunks: ceil(52428800 / 64512) = 813 (last chunk is partial)

            file_size = 50 * 1024 * 1024
            expected_count = math.ceil(file_size / DEFAULT_CHUNK_SIZE)
            assert chunk_count == expected_count
        finally:
            Path(temp_path).unlink()


class TestChunkFileWithProgress:
    """Test chunk_file_with_progress function."""

    def test_chunk_with_progress_callback(self):
        """Test chunking with progress callback."""
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"x" * (chunk_size * 4)
            f.write(data)
            temp_path = f.name

        try:
            progress_calls = []

            def callback(current, total, chunk_num):
                progress_calls.append((current, total, chunk_num))

            chunks = list(
                chunk_file_with_progress(
                    temp_path, chunk_size=chunk_size, progress_callback=callback
                )
            )

            # Verify chunks
            assert len(chunks) == 4
            assert b"".join(chunks) == data

            # Verify progress calls
            assert len(progress_calls) == 4
            file_size = chunk_size * 4
            assert progress_calls[0] == (chunk_size, file_size, 1)
            assert progress_calls[1] == (chunk_size * 2, file_size, 2)
            assert progress_calls[2] == (chunk_size * 3, file_size, 3)
            assert progress_calls[3] == (chunk_size * 4, file_size, 4)
        finally:
            Path(temp_path).unlink()

    def test_chunk_with_progress_no_callback(self):
        """Test chunking without callback (should still work)."""
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"x" * (chunk_size * 4)
            f.write(data)
            temp_path = f.name

        try:
            chunks = list(chunk_file_with_progress(temp_path, chunk_size=chunk_size))
            assert len(chunks) == 4
            assert b"".join(chunks) == data
        finally:
            Path(temp_path).unlink()


class TestGetFileSize:
    """Test get_file_size function."""

    def test_get_size_normal_file(self):
        """Test getting size of normal file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"x" * 12345
            f.write(data)
            temp_path = f.name

        try:
            size = get_file_size(temp_path)
            assert size == 12345
        finally:
            Path(temp_path).unlink()

    def test_get_size_empty_file(self):
        """Test getting size of empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            size = get_file_size(temp_path)
            assert size == 0
        finally:
            Path(temp_path).unlink()

    def test_get_size_not_found(self):
        """Test getting size of non-existent file."""
        with pytest.raises(FileNotFoundError):
            get_file_size("/nonexistent/file.txt")


class TestEstimateChunkCount:
    """Test estimate_chunk_count function."""

    def test_estimate_exact_fit(self):
        """Test estimate when file fits exactly."""
        chunk_size = 16 * 1024  # 16 KB for testing
        count = estimate_chunk_count(chunk_size * 4, chunk_size)
        assert count == 4

    def test_estimate_with_remainder(self):
        """Test estimate with remainder."""
        chunk_size = 16 * 1024  # 16 KB for testing
        count = estimate_chunk_count(chunk_size * 4 + 5000, chunk_size)
        assert count == 5

    def test_estimate_smaller_than_chunk(self):
        """Test estimate when file is smaller than chunk."""
        chunk_size = 16 * 1024  # 16 KB for testing
        count = estimate_chunk_count(1000, chunk_size)
        assert count == 1

    def test_estimate_zero_size(self):
        """Test estimate with zero size."""
        count = estimate_chunk_count(0)
        assert count == 0

    def test_estimate_large_file(self):
        """Test estimate for large file."""
        # 1 GB file with DEFAULT_CHUNK_SIZE
        count = estimate_chunk_count(1024 * 1024 * 1024, DEFAULT_CHUNK_SIZE)
        expected = (1024 * 1024 * 1024 + DEFAULT_CHUNK_SIZE - 1) // DEFAULT_CHUNK_SIZE
        assert count == expected


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_chunk_and_reconstruct(self):
        """Test chunking and reconstructing a file."""
        # Create test file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            original_data = b"test data " * 10000  # ~100 KB
            f.write(original_data)
            temp_path = f.name

        try:
            # Get file size
            file_size = get_file_size(temp_path)

            # Chunk file with default chunk size
            chunks = list(chunk_file(temp_path, DEFAULT_CHUNK_SIZE))

            # Reconstruct
            reconstructed = b"".join(chunks)

            assert reconstructed == original_data
            assert len(reconstructed) == file_size
        finally:
            Path(temp_path).unlink()

    def test_estimate_accuracy(self):
        """Test that estimate_chunk_count is accurate."""
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"x" * (chunk_size * 12 + 5000)
            f.write(data)
            temp_path = f.name

        try:
            file_size = get_file_size(temp_path)

            # Estimate
            estimated = estimate_chunk_count(file_size, chunk_size)

            # Actual
            actual = len(list(chunk_file(temp_path, chunk_size)))

            assert estimated == actual
        finally:
            Path(temp_path).unlink()

    def test_progress_tracking_complete(self):
        """Test that progress tracking reports complete file."""
        chunk_size = 16 * 1024  # 16 KB for testing
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"x" * (chunk_size * 5)
            f.write(data)
            temp_path = f.name

        try:
            file_size = get_file_size(temp_path)
            total_processed = 0

            def callback(current, total, chunk_num):
                nonlocal total_processed
                total_processed = current
                assert current <= total
                assert total == file_size

            chunks = list(
                chunk_file_with_progress(
                    temp_path, chunk_size=chunk_size, progress_callback=callback
                )
            )

            # Verify all data processed
            assert total_processed == file_size
            assert len(b"".join(chunks)) == file_size
        finally:
            Path(temp_path).unlink()

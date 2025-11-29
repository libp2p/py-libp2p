"""
File chunking utilities for Merkle DAG.

This module provides functions to split files into chunks for storage
in a Merkle DAG structure, enabling efficient storage and transfer of
large files.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

# Default chunk size: 63 KB (py-libp2p accepts less than 64 KB)
DEFAULT_CHUNK_SIZE = 63 * 1024


def chunk_bytes(data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[bytes]:
    """
    Split bytes into fixed-size chunks.

    Args:
        data: Data to chunk
        chunk_size: Size of each chunk in bytes

    Returns:
        List of chunks

    Example:
        >>> data = b"x" * 1_000_000  # 1 MB
        >>> chunks = chunk_bytes(data, chunk_size=256*1024)
        >>> print(f"Split into {len(chunks)} chunks")
        Split into 4 chunks
        >>> print(f"Last chunk size: {len(chunks[-1])}")
        Last chunk size: 230400

    """
    if not data:
        return []

    chunks = []
    offset = 0

    while offset < len(data):
        chunk = data[offset : offset + chunk_size]
        chunks.append(chunk)
        offset += chunk_size

    return chunks


def chunk_file(file_path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
    """
    Stream file in chunks (memory efficient).

    This is the recommended way to chunk large files as it doesn't
    load the entire file into memory.

    Args:
        file_path: Path to file
        chunk_size: Size of each chunk in bytes

    Yields:
        File chunks

    Raises:
        FileNotFoundError: If file doesn't exist

    Example:
        >>> for i, chunk in enumerate(chunk_file('large_file.bin')):
        ...     print(f"Processing chunk {i}: {len(chunk)} bytes")
        ...     # Process chunk

    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def estimate_chunk_count(file_size: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
    """
    Estimate number of chunks for a given file size.

    Args:
        file_size: Size of file in bytes
        chunk_size: Chunk size in bytes (defaults to DEFAULT_CHUNK_SIZE)

    Returns:
        Estimated number of chunks

    Example:
        >>> estimate_chunk_count(1024 * 1024)  # 1 MB file
        17
        >>> estimate_chunk_count(500 * 1024 * 1024)  # 500 MB file
        8127

    """
    if file_size < 0:
        raise ValueError(f"file_size must be non-negative, got {file_size}")

    if file_size == 0:
        return 0

    # Round up division
    return (file_size + chunk_size - 1) // chunk_size


def get_file_size(file_path: str) -> int:
    """
    Get the size of a file.

    Args:
        file_path: Path to file

    Returns:
        File size in bytes

    Raises:
        FileNotFoundError: If file doesn't exist

    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    return path.stat().st_size


def chunk_file_with_progress(
    file_path: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> Iterator[bytes]:
    """
    Stream file in chunks with progress tracking.

    Args:
        file_path: Path to file
        chunk_size: Size of each chunk in bytes
        progress_callback: Optional callback(current_byte, total_bytes, chunk_num)

    Yields:
        File chunks

    Example:
        >>> def on_progress(current, total, chunk_num):
        ...     percent = (current / total) * 100
        ...     print(f"Progress: {percent:.1f}% (chunk {chunk_num})")
        >>> for chunk in chunk_file_with_progress(
        ...     'file.bin', progress_callback=on_progress
        ... ):
        ...     process(chunk)

    """
    file_size = get_file_size(file_path)
    bytes_read = 0
    chunk_num = 0

    for chunk in chunk_file(file_path, chunk_size):
        bytes_read += len(chunk)
        chunk_num += 1

        if progress_callback:
            progress_callback(bytes_read, file_size, chunk_num)

        yield chunk


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "chunk_bytes",
    "chunk_file",
    "chunk_file_with_progress",
    "estimate_chunk_count",
    "get_file_size",
]

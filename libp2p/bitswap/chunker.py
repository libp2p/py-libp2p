"""
File chunking utilities for Merkle DAG.

This module provides functions to split files into chunks for storage
in a Merkle DAG structure, enabling efficient storage and transfer of
large files.
"""

from pathlib import Path
from typing import Callable, Iterator, List, Optional

# Default chunk size: 256 KB (IPFS default)
DEFAULT_CHUNK_SIZE = 256 * 1024

# Minimum chunk size: 64 KB
MIN_CHUNK_SIZE = 64 * 1024

# Maximum chunk size: 1 MB
MAX_CHUNK_SIZE = 1024 * 1024


def chunk_bytes(data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[bytes]:
    """
    Split bytes into fixed-size chunks.

    Args:
        data: Data to chunk
        chunk_size: Size of each chunk in bytes

    Returns:
        List of chunks

    Raises:
        ValueError: If chunk_size is invalid

    Example:
        >>> data = b"x" * 1_000_000  # 1 MB
        >>> chunks = chunk_bytes(data, chunk_size=256*1024)
        >>> print(f"Split into {len(chunks)} chunks")
        Split into 4 chunks
        >>> print(f"Last chunk size: {len(chunks[-1])}")
        Last chunk size: 230400

    """
    if chunk_size < MIN_CHUNK_SIZE:
        raise ValueError(
            f"chunk_size must be at least {MIN_CHUNK_SIZE}, got {chunk_size}"
        )
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(
            f"chunk_size must be at most {MAX_CHUNK_SIZE}, got {chunk_size}"
        )

    if not data:
        return []

    chunks = []
    offset = 0

    while offset < len(data):
        chunk = data[offset : offset + chunk_size]
        chunks.append(chunk)
        offset += chunk_size

    return chunks


def chunk_file(
    file_path: str, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Iterator[bytes]:
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
        ValueError: If chunk_size is invalid

    Example:
        >>> for i, chunk in enumerate(chunk_file('large_file.bin')):
        ...     print(f"Processing chunk {i}: {len(chunk)} bytes")
        ...     # Process chunk

    """
    if chunk_size < MIN_CHUNK_SIZE:
        raise ValueError(
            f"chunk_size must be at least {MIN_CHUNK_SIZE}, got {chunk_size}"
        )
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(
            f"chunk_size must be at most {MAX_CHUNK_SIZE}, got {chunk_size}"
        )

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def optimal_chunk_size(file_size: int) -> int:
    """
    Determine optimal chunk size based on file size.

    Strategy:
    - Small files (<1MB): 64 KB chunks
    - Medium files (1MB-100MB): 256 KB chunks (default)
    - Large files (>100MB): 1 MB chunks

    This balances between:
    - Too many small chunks (high overhead)
    - Too few large chunks (poor parallelization)

    Args:
        file_size: Size of file in bytes

    Returns:
        Optimal chunk size in bytes

    Example:
        >>> optimal_chunk_size(500 * 1024)  # 500 KB
        65536
        >>> optimal_chunk_size(50 * 1024 * 1024)  # 50 MB
        262144
        >>> optimal_chunk_size(500 * 1024 * 1024)  # 500 MB
        1048576

    """
    if file_size < 0:
        raise ValueError(f"file_size must be non-negative, got {file_size}")

    if file_size < 1024 * 1024:  # < 1 MB
        return 64 * 1024  # 64 KB
    elif file_size < 100 * 1024 * 1024:  # < 100 MB
        return 256 * 1024  # 256 KB (IPFS default)
    else:  # >= 100 MB
        return 1024 * 1024  # 1 MB


def estimate_chunk_count(file_size: int, chunk_size: Optional[int] = None) -> int:
    """
    Estimate number of chunks for a given file size.

    Args:
        file_size: Size of file in bytes
        chunk_size: Chunk size in bytes (auto-selected if None)

    Returns:
        Estimated number of chunks

    Example:
        >>> estimate_chunk_count(1024 * 1024)  # 1 MB file
        4
        >>> estimate_chunk_count(500 * 1024 * 1024)  # 500 MB file
        500

    """
    if file_size < 0:
        raise ValueError(f"file_size must be non-negative, got {file_size}")

    if file_size == 0:
        return 0

    if chunk_size is None:
        chunk_size = optimal_chunk_size(file_size)

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
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
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
        >>> for chunk in chunk_file_with_progress('file.bin', progress_callback=on_progress):
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


# Type hints for Python 3.9+
from typing import Callable, Optional

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MIN_CHUNK_SIZE",
    "MAX_CHUNK_SIZE",
    "chunk_bytes",
    "chunk_file",
    "chunk_file_with_progress",
    "optimal_chunk_size",
    "estimate_chunk_count",
    "get_file_size",
]

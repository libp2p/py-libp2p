"""
Merkle DAG manager for file operations.

This module provides a high-level API for adding and fetching files
using the Bitswap protocol with automatic chunking, linking, and
multi-block resolution.
"""

import inspect
import logging
from typing import Awaitable, Callable, List, Optional, Tuple, Union

from .block_store import BlockStore
from .chunker import (
    chunk_bytes,
    chunk_file,
    estimate_chunk_count,
    get_file_size,
    optimal_chunk_size,
)
from .cid import CODEC_DAG_PB, CODEC_RAW, compute_cid_v1, verify_cid
from .client import BitswapClient
from .dag_pb import (
    create_file_node,
    decode_dag_pb,
    is_file_node,
)

logger = logging.getLogger(__name__)


# Type alias for progress callbacks (sync or async)
ProgressCallback = Union[
    Callable[[int, int, str], None],
    Callable[[int, int, str], Awaitable[None]],
]


async def _call_progress_callback(
    callback: Optional[ProgressCallback],
    current: int,
    total: int,
    status: str,
) -> None:
    """Call a progress callback, handling both sync and async callbacks."""
    if callback is None:
        return

    if inspect.iscoroutinefunction(callback):
        await callback(current, total, status)
    else:
        callback(current, total, status)


class MerkleDag:
    """
    Merkle DAG manager for file operations.

    Provides high-level API for adding and fetching files with automatic
    chunking, link creation, and recursive block fetching.

    Example:
        >>> from libp2p import new_host
        >>> from libp2p.bitswap import BitswapClient, MemoryBlockStore, MerkleDag
        >>> import trio
        >>>
        >>> async def main():
        ...     host = new_host()
        ...     async with host.run(["/ip4/0.0.0.0/tcp/0"]):
        ...         store = MemoryBlockStore()
        ...         bitswap = BitswapClient(host, store)
        ...         await bitswap.start()
        ...
        ...         dag = MerkleDag(bitswap)
        ...
        ...         # Add a large file (auto-chunked)
        ...         root_cid = await dag.add_file('movie.mp4')
        ...         print(f"Share: {root_cid.hex()}")
        ...
        ...         # Fetch file (auto-resolves all chunks)
        ...         data = await dag.fetch_file(root_cid)
        ...         open('downloaded.mp4', 'wb').write(data)
        ...
        >>> trio.run(main)

    """

    def __init__(
        self, bitswap: BitswapClient, block_store: Optional[BlockStore] = None
    ):
        """
        Initialize Merkle DAG manager.

        Args:
            bitswap: Bitswap client for block exchange
            block_store: Optional block store (uses bitswap's store if None)

        """
        self.bitswap = bitswap
        self.block_store = block_store or bitswap.block_store

    async def add_file(
        self,
        file_path: str,
        chunk_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> bytes:
        """
        Add a file to the DAG.

        Automatically chunks large files and creates link structure.
        Small files are stored as single blocks.

        Args:
            file_path: Path to file
            chunk_size: Optional chunk size (auto-selected if None)
            progress_callback: Optional callback(current, total, status)

        Returns:
            Root CID of the file

        Raises:
            FileNotFoundError: If file doesn't exist
            BlockTooLargeError: If a single chunk exceeds MAX_BLOCK_SIZE

        Example:
            >>> async def progress(current, total, status):
            ...     print(f"{status}: {current}/{total}")
            >>> root_cid = await dag.add_file('movie.mp4', progress_callback=progress)
            >>> print(f"Share this: {root_cid.hex()}")

        """
        # Get file size
        file_size = get_file_size(file_path)
        logger.info(f"Adding file: {file_path} ({file_size} bytes)")

        # Determine chunk size
        if chunk_size is None:
            chunk_size = optimal_chunk_size(file_size)

        logger.debug(f"Using chunk size: {chunk_size} bytes")

        # If file is small enough, store as single RAW block
        if file_size <= chunk_size:
            logger.debug("File fits in single block")
            with open(file_path, "rb") as f:
                data = f.read()

            cid = compute_cid_v1(data, codec=CODEC_RAW)
            await self.bitswap.add_block(cid, data)

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, file_size, file_size, "completed"
                )

            logger.info(f"Added file as single block: {cid.hex()[:16]}...")
            return cid

        # Chunk the file
        logger.debug(f"Chunking file into ~{estimate_chunk_count(file_size, chunk_size)} chunks")

        chunks_data: List[Tuple[bytes, int]] = []
        bytes_processed = 0

        # Process file in chunks (memory efficient)
        for i, chunk_data in enumerate(chunk_file(file_path, chunk_size)):
            # Compute CID for chunk
            chunk_cid = compute_cid_v1(chunk_data, codec=CODEC_RAW)

            # Store chunk
            await self.bitswap.add_block(chunk_cid, chunk_data)

            # Track chunk info
            chunks_data.append((chunk_cid, len(chunk_data)))
            bytes_processed += len(chunk_data)

            # Progress callback
            if progress_callback:
                await _call_progress_callback(
                    progress_callback,
                    bytes_processed,
                    file_size,
                    f"chunking ({i + 1} chunks)",
                )

            logger.debug(
                f"Stored chunk {i}: {chunk_cid.hex()[:16]}... "
                f"({len(chunk_data)} bytes)"
            )

        # Create root node with links to all chunks
        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "creating root node"
            )

        root_data = create_file_node(chunks_data)
        root_cid = compute_cid_v1(root_data, codec=CODEC_DAG_PB)
        await self.bitswap.add_block(root_cid, root_data)

        logger.info(
            f"Added file with {len(chunks_data)} chunks. "
            f"Root CID: {root_cid.hex()[:16]}..."
        )

        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "completed"
            )

        return root_cid

    async def add_bytes(
        self,
        data: bytes,
        chunk_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> bytes:
        """
        Add bytes to the DAG (similar to add_file but for in-memory data).

        Args:
            data: Data to add
            chunk_size: Optional chunk size (auto-selected if None)
            progress_callback: Optional callback(current, total, status)

        Returns:
            Root CID

        Example:
            >>> data = b"x" * (10 * 1024 * 1024)  # 10 MB
            >>> root_cid = await dag.add_bytes(data)

        """
        file_size = len(data)
        logger.info(f"Adding {file_size} bytes")

        # Determine chunk size
        if chunk_size is None:
            chunk_size = optimal_chunk_size(file_size)

        # If data is small, store as single block
        if file_size <= chunk_size:
            cid = compute_cid_v1(data, codec=CODEC_RAW)
            await self.bitswap.add_block(cid, data)

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, file_size, file_size, "completed"
                )

            return cid

        # Chunk the data
        chunks = chunk_bytes(data, chunk_size)
        chunks_data: List[Tuple[bytes, int]] = []

        for i, chunk_data in enumerate(chunks):
            chunk_cid = compute_cid_v1(chunk_data, codec=CODEC_RAW)
            await self.bitswap.add_block(chunk_cid, chunk_data)
            chunks_data.append((chunk_cid, len(chunk_data)))

            if progress_callback:
                bytes_processed = sum(size for _, size in chunks_data)
                await _call_progress_callback(
                    progress_callback,
                    bytes_processed,
                    file_size,
                    f"chunking ({i + 1}/{len(chunks)})",
                )

        # Create root node
        root_data = create_file_node(chunks_data)
        root_cid = compute_cid_v1(root_data, codec=CODEC_DAG_PB)
        await self.bitswap.add_block(root_cid, root_data)

        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "completed"
            )

        return root_cid

    async def fetch_file(
        self,
        root_cid: bytes,
        peer_id: Optional[object] = None,
        timeout: float = 30.0,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> bytes:
        """
        Fetch a file from the DAG.

        Automatically resolves links and fetches all chunks. Works with both
        single-block files and multi-chunk files.

        Args:
            root_cid: Root CID of the file
            peer_id: Optional specific peer to fetch from
            timeout: Timeout per block in seconds
            progress_callback: Optional callback(current, total, status)

        Returns:
            Complete file data

        Raises:
            BlockNotFoundError: If any block cannot be found
            ValueError: If CID verification fails

        Example:
            >>> def progress(current, total, status):
            ...     percent = (current / total) * 100 if total > 0 else 0
            ...     print(f"{status}: {percent:.1f}%")
            >>> data = await dag.fetch_file(root_cid, progress_callback=progress)
            >>> open('downloaded_movie.mp4', 'wb').write(data)

        """
        logger.info(f"Fetching file: {root_cid.hex()[:16]}...")

        # Get root block
        root_data = await self.bitswap.get_block(root_cid, peer_id, timeout)

        # Verify root block
        if not verify_cid(root_cid, root_data):
            raise ValueError(f"Root block verification failed: {root_cid.hex()}")

        # Check if it's a DAG-PB file node
        if is_file_node(root_data):
            logger.debug("Root is a DAG-PB file node, resolving chunks...")

            # Decode to get links and metadata
            links, unixfs_data = decode_dag_pb(root_data)

            if not links:
                # File with inline data (small file)
                logger.debug("File has inline data")
                if unixfs_data and unixfs_data.data:
                    return unixfs_data.data
                return b""

            # File with multiple chunks
            total_size = unixfs_data.filesize if unixfs_data else 0
            logger.debug(f"File has {len(links)} chunks, total size: {total_size}")

            file_data = b""
            bytes_fetched = 0

            # Fetch each chunk
            for i, link in enumerate(links):
                if progress_callback:
                    await _call_progress_callback(
                        progress_callback,
                        bytes_fetched,
                        total_size,
                        f"fetching chunk {i + 1}/{len(links)}",
                    )

                # Fetch chunk
                chunk_data = await self.bitswap.get_block(
                    link.cid, peer_id, timeout
                )

                # Verify chunk
                if not verify_cid(link.cid, chunk_data):
                    raise ValueError(
                        f"Chunk verification failed: {link.cid.hex()}"
                    )

                file_data += chunk_data
                bytes_fetched += len(chunk_data)

                logger.debug(
                    f"Fetched chunk {i + 1}/{len(links)}: "
                    f"{link.cid.hex()[:16]}... ({len(chunk_data)} bytes)"
                )

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, total_size, total_size, "completed"
                )

            logger.info(f"Fetched file: {len(file_data)} bytes")
            return file_data

        # Not a DAG-PB file node - return as raw data
        logger.debug("Root is a raw block, returning directly")
        return root_data

    async def get_file_info(
        self, root_cid: bytes, peer_id: Optional[object] = None, timeout: float = 30.0
    ) -> dict:
        """
        Get information about a file without downloading it.

        Args:
            root_cid: Root CID of the file
            peer_id: Optional specific peer to fetch from
            timeout: Timeout in seconds (default: 30.0)

        Returns:
            Dictionary with file information:
            - size: Total file size in bytes
            - chunks: Number of chunks
            - chunk_sizes: List of chunk sizes

        Example:
            >>> info = await dag.get_file_info(root_cid)
            >>> print(f"File size: {info['size']} bytes")
            >>> print(f"Chunks: {info['chunks']}")

        """
        # Get root block
        root_data = await self.bitswap.get_block(root_cid, peer_id, timeout)

        # Check if it's a DAG-PB file node
        if is_file_node(root_data):
            links, unixfs_data = decode_dag_pb(root_data)

            if not links:
                # Small file with inline data
                data_size = len(unixfs_data.data) if unixfs_data and unixfs_data.data else 0
                return {"size": data_size, "chunks": 0, "chunk_sizes": []}

            # Multi-chunk file
            total_size = unixfs_data.filesize if unixfs_data else sum(
                link.size for link in links
            )
            chunk_sizes = [link.size for link in links]

            return {
                "size": total_size,
                "chunks": len(links),
                "chunk_sizes": chunk_sizes,
            }

        # Single raw block
        return {"size": len(root_data), "chunks": 1, "chunk_sizes": [len(root_data)]}


__all__ = ["MerkleDag"]

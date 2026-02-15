"""
Merkle DAG manager for file operations.

This module provides a high-level API for adding and fetching files
using the Bitswap protocol with automatic chunking, linking, and
multi-block resolution.

"""

from collections.abc import Awaitable, Callable
import inspect
import logging
from typing import Union

from libp2p.peer.id import ID as PeerID

from .block_store import BlockStore
from .chunker import (
    DEFAULT_CHUNK_SIZE,
    chunk_bytes,
    chunk_file,
    estimate_chunk_count,
    get_file_size,
)
from .cid import (
    CODEC_DAG_PB,
    CODEC_RAW,
    compute_cid_v1,
    verify_cid,
)
from .client import BitswapClient
from .dag_pb import (
    create_file_node,
    decode_dag_pb,
    is_directory_node,
    is_file_node,
)

logger = logging.getLogger(__name__)


# Type alias for progress callbacks (sync or async)
ProgressCallback = Union[
    Callable[[int, int, str], None],
    Callable[[int, int, str], Awaitable[None]],
]


async def _call_progress_callback(
    callback: ProgressCallback | None,
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

    def __init__(self, bitswap: BitswapClient, block_store: BlockStore | None = None):
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
        chunk_size: int | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        wrap_with_directory: bool = True,
    ) -> bytes:
        """
        Add a file to the DAG.

        Automatically chunks large files and creates link structure.
        Small files are stored as single blocks.

        Args:
            file_path: Path to file
            chunk_size: Optional chunk size (auto-selected if None)
            progress_callback: Optional callback(current, total, status)
            wrap_with_directory: If True, wraps file in a directory node with filename
                                 (IPFS-standard way, enables filename preservation)

        Returns:
            Root CID of the file (or wrapping directory if wrap_with_directory=True)

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
            chunk_size = DEFAULT_CHUNK_SIZE

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

            # Wrap in directory if requested
            if wrap_with_directory:
                import os

                from .dag_pb import create_directory_node

                filename = os.path.basename(file_path)
                logger.info(
                    f"Wrapping single-block file in directory with name: {filename}"
                )

                dir_data = create_directory_node([(filename, cid, file_size)])
                dir_cid = compute_cid_v1(dir_data, codec=CODEC_DAG_PB)
                await self.bitswap.add_block(dir_cid, dir_data)

                logger.info(
                    f"Created directory wrapper. Directory CID: {dir_cid.hex()[:16]}..."
                )
                return dir_cid

            return cid

        # Chunk the file
        estimated_chunks = estimate_chunk_count(file_size, chunk_size)
        logger.debug(f"Chunking file into ~{estimated_chunks} chunks")
        logger.info("=== Starting file chunking process ===")

        chunks_data: list[tuple[bytes, int]] = []
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

            # Enhanced logging with full CID
            logger.info(
                f"Chunk {i + 1}: CID={chunk_cid.hex()}, "
                f"Size={len(chunk_data)} bytes, "
                f"Progress={bytes_processed}/{file_size}"
            )
            logger.debug(
                f"Stored chunk {i}: {chunk_cid.hex()[:16]}... ({len(chunk_data)} bytes)"
            )

        # Create root node with links to all chunks
        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "creating root node"
            )

        root_data = create_file_node(chunks_data)
        root_cid = compute_cid_v1(root_data, codec=CODEC_DAG_PB)
        await self.bitswap.add_block(root_cid, root_data)

        # Enhanced logging for root CID
        logger.info("=== File chunking completed ===")
        logger.info(f"Root CID: {root_cid.hex()} (Links to {len(chunks_data)} chunks)")
        logger.info(f"Total file size: {file_size} bytes")
        logger.info("=== Chunk CIDs ===")
        for i, (chunk_cid, chunk_size) in enumerate(chunks_data):
            logger.info(f"  Chunk {i}: {chunk_cid.hex()} ({chunk_size} bytes)")
        logger.info("=" * 50)

        logger.info(
            f"Added file with {len(chunks_data)} chunks. "
            f"Root CID: {root_cid.hex()[:16]}..."
        )

        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "completed"
            )

        # Wrap in directory if requested (IPFS-standard way for filename preservation)
        if wrap_with_directory:
            import os

            from .dag_pb import create_directory_node

            filename = os.path.basename(file_path)
            logger.info(f"Wrapping file in directory with name: {filename}")

            # Create directory node with single entry pointing to the file
            dir_data = create_directory_node([(filename, root_cid, file_size)])
            dir_cid = compute_cid_v1(dir_data, codec=CODEC_DAG_PB)
            await self.bitswap.add_block(dir_cid, dir_data)

            logger.info(
                f"Created directory wrapper. Directory CID: {dir_cid.hex()[:16]}..."
            )
            return dir_cid

        return root_cid

    async def add_bytes(
        self,
        data: bytes,
        chunk_size: int | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
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
            chunk_size = DEFAULT_CHUNK_SIZE

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
        chunks_data: list[tuple[bytes, int]] = []

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
        peer_id: PeerID | None = None,
        timeout: float = 30.0,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> tuple[bytes, str | None]:
        """
        Fetch a file from the DAG.

        Automatically resolves links and fetches all chunks. Works with both
        single-block files and multi-chunk files. Everything is handled
        automatically - just provide the root CID!

        The method automatically:
        - Detects directory wrappers and extracts filename
        - Fetches and decodes the root block
        - Determines file size and number of chunks
        - Fetches all chunks in sequence
        - Verifies integrity of all blocks
        - Reconstructs the complete file

        Args:
            root_cid: Root CID of the file (or directory wrapper)
            peer_id: Optional specific peer to fetch from
            timeout: Timeout per block in seconds
            progress_callback: Optional callback(current, total, status)
                              Receives metadata automatically in first call

        Returns:
            Tuple of (file_data, filename) where filename is None if not
            wrapped in directory

        Raises:
            BlockNotFoundError: If any block cannot be found
            ValueError: If CID verification fails

        Example:
            >>> # Simple usage - just provide root CID
            >>> data, filename = await dag.fetch_file(root_cid)
            >>> save_path = filename or 'downloaded_file'
            >>> open(save_path, 'wb').write(data)

            >>> # With progress tracking
            >>> def progress(current, total, status):
            ...     percent = (current / total) * 100 if total > 0 else 0
            ...     print(f"{status}: {percent:.1f}%")
            >>> data, filename = await dag.fetch_file(
            ...     root_cid, progress_callback=progress
            ... )

        """
        logger.info(f"Fetching file: {root_cid.hex()[:16]}...")
        logger.info(f"=== Starting file fetch for CID: {root_cid.hex()} ===")

        # Get root block
        root_data = await self.bitswap.get_block(root_cid, peer_id, timeout)

        # Verify root block
        if not verify_cid(root_cid, root_data):
            raise ValueError(f"Root block verification failed: {root_cid.hex()}")

        # Check if it's a directory wrapper (IPFS-standard way for filename)
        filename = None
        actual_file_cid = root_cid
        actual_file_data = root_data

        if is_directory_node(root_data):
            logger.info("Root is a directory node, extracting file entry...")
            links, _ = decode_dag_pb(root_data)

            if links:
                # Get the first (and typically only) file entry
                first_link = links[0]
                filename = first_link.name if first_link.name else None
                actual_file_cid = first_link.cid

                logger.info(f"Extracted filename: {filename}")
                logger.info(f"Actual file CID: {actual_file_cid.hex()[:16]}...")

                # Fetch the actual file block
                actual_file_data = await self.bitswap.get_block(
                    actual_file_cid, peer_id, timeout
                )

                if not verify_cid(actual_file_cid, actual_file_data):
                    raise ValueError(
                        f"File block verification failed: {actual_file_cid.hex()}"
                    )

        # Now process the actual file data
        # Check if it's a DAG-PB file node
        if is_file_node(actual_file_data):
            logger.debug("Root is a DAG-PB file node, resolving chunks...")

            # Decode to get links and metadata
            links, unixfs_data = decode_dag_pb(actual_file_data)

            if not links:
                # File with inline data (small file)
                logger.debug("File has inline data")
                file_data = (
                    unixfs_data.data if unixfs_data and unixfs_data.data else b""
                )

                # Notify progress callback with metadata
                if progress_callback:
                    await _call_progress_callback(
                        progress_callback,
                        len(file_data),
                        len(file_data),
                        f"metadata: size={len(file_data)}, chunks=0",
                    )

                return file_data, filename

            # File with multiple chunks
            total_size = unixfs_data.filesize if unixfs_data else 0
            logger.debug(f"File has {len(links)} chunks, total size: {total_size}")
            logger.info(
                f"Fetching multi-chunk file: {len(links)} chunks, {total_size} bytes"
            )
            logger.info("=== Chunk CIDs to fetch ===")
            for i, link in enumerate(links):
                logger.info(f"  Chunk {i}: {link.cid.hex()} ({link.size} bytes)")
            logger.info("=" * 50)

            # Notify progress callback with file metadata at the start
            if progress_callback:
                await _call_progress_callback(
                    progress_callback,
                    0,
                    total_size,
                    f"metadata: size={total_size}, chunks={len(links)}",
                )

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

                logger.info(
                    f"Fetching chunk {i + 1}/{len(links)}: CID={link.cid.hex()}"
                )

                # Fetch chunk
                chunk_data = await self.bitswap.get_block(link.cid, peer_id, timeout)

                # Verify chunk
                if not verify_cid(link.cid, chunk_data):
                    raise ValueError(f"Chunk verification failed: {link.cid.hex()}")

                file_data += chunk_data
                bytes_fetched += len(chunk_data)

                logger.info(
                    f"✓ Chunk {i + 1} fetched and verified: "
                    f"{len(chunk_data)} bytes (total: {bytes_fetched}/{total_size})"
                )
                logger.debug(
                    f"Fetched chunk {i + 1}/{len(links)}: "
                    f"{link.cid.hex()[:16]}... ({len(chunk_data)} bytes)"
                )

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, total_size, total_size, "completed"
                )

            logger.info("=== File fetch completed ===")
            logger.info(f"Total bytes fetched: {len(file_data)}")
            logger.info(f"All {len(links)} chunks verified successfully")
            logger.info("=" * 50)
            logger.info(f"Fetched file: {len(file_data)} bytes")
            return file_data, filename

        # Not a DAG-PB file node - return as raw data
        logger.debug("Root is a raw block, returning directly")
        return actual_file_data, filename

    async def get_file_info(
        self, root_cid: bytes, peer_id: PeerID | None = None, timeout: float = 30.0
    ) -> dict[str, int | list[int]]:
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
                data_size = (
                    len(unixfs_data.data) if unixfs_data and unixfs_data.data else 0
                )
                return {"size": data_size, "chunks": 0, "chunk_sizes": []}

            # Multi-chunk file
            total_size = (
                unixfs_data.filesize
                if unixfs_data
                else sum(link.size for link in links)
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

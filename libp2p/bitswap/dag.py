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

from .block_service import BlockService
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
    CIDInput,
    cid_to_bytes,
    compute_cid_v1,
    format_cid_for_display,
    verify_cid,
)
from .client import BitswapClient
from .dag_pb import (
    balanced_layout,
    create_leaf_node,
    decode_dag_pb,
    is_directory_node,
    is_file_node,
)
from .errors import BlockNotFoundError

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
        ...         print(f"Share: {cid_to_text(root_cid)}")
        ...
        ...         # Fetch file (auto-resolves all chunks)
        ...         data = await dag.fetch_file(root_cid)
        ...         open('downloaded.mp4', 'wb').write(data)
        ...
        >>> trio.run(main)

    """

    def __init__(
        self,
        bitswap: BitswapClient,
        block_store: BlockStore | None = None,
        block_service: BlockService | None = None,
    ):
        """
        Initialize Merkle DAG manager.

        Args:
            bitswap: Bitswap client for block exchange
            block_store: Optional block store (uses bitswap's store if None)
            block_service: Optional BlockService for transparent local→network
                           fallback with auto-caching. When provided, all block
                           reads/writes go through it instead of bitswap directly.
                           Construct with: BlockService(your_store, bitswap)

        """
        self.bitswap = bitswap
        self.block_store = block_store or bitswap.block_store
        # If a BlockService is provided use it; otherwise fall back to
        # calling bitswap directly (existing behaviour, no regression).
        self._service: BlockService | None = block_service

    # ── private routing helpers ───────────────────────────────────────────────

    async def _put_block(self, cid: CIDInput, data: bytes) -> None:
        """Store a block. Routes through BlockService when available."""
        if self._service is not None:
            await self._service.put_block(cid, data)
        else:
            await self.bitswap.add_block(cid, data)

    async def _get_block(
        self,
        cid: CIDInput,
        peer_id: PeerID | None = None,
        timeout: float = 30.0,
    ) -> bytes:
        """Fetch a block. Routes through BlockService when available."""
        if self._service is not None:
            data = await self._service.get_block(cid, peer_id=peer_id, timeout=timeout)
            if data is None:
                from .cid import format_cid_for_display, cid_to_bytes
                raise BlockNotFoundError(
                    f"Block not found: {format_cid_for_display(cid_to_bytes(cid))}"
                )
            return data
        return await self.bitswap.get_block(cid, peer_id, timeout)

    async def _get_blocks_batch(
        self,
        cids: list[CIDInput],
        peer_id: PeerID | None = None,
        timeout: float = 30.0,
        batch_size: int = 32,
    ) -> dict[bytes, bytes]:
        """Batch-fetch blocks. Routes through BlockService when available."""
        if self._service is not None:
            return await self._service.get_blocks_batch(
                cids, peer_id=peer_id, timeout=timeout, batch_size=batch_size
            )
        return await self.bitswap.get_blocks_batch(
            cids, peer_id=peer_id, timeout=timeout, batch_size=batch_size
        )

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
            >>> print(f"Share this: {cid_to_text(root_cid)}")

        """
        # Get file size
        file_size = get_file_size(file_path)
        logger.info(f"Adding file: {file_path} ({file_size} bytes)")

        # Determine chunk size
        if chunk_size is None:
            chunk_size = DEFAULT_CHUNK_SIZE

        logger.debug(f"Using chunk size: {chunk_size} bytes")

        # If file is small enough, store as single dag-pb leaf block
        if file_size <= chunk_size:
            logger.debug("File fits in single block")

            with open(file_path, "rb") as f:
                data = f.read()

            leaf_block = create_leaf_node(data)
            cid = compute_cid_v1(leaf_block, codec=CODEC_DAG_PB)

            await self._put_block(cid, leaf_block)

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, file_size, file_size, "completed"
                )

            logger.info(
                f"Added file as single block: {format_cid_for_display(cid, max_len=16)}"
            )

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
                await self._put_block(dir_cid, dir_data)

                logger.info(
                    f"Created directory wrapper. Directory CID: "
                    f"{format_cid_for_display(dir_cid, max_len=16)}"
                )
                return dir_cid

            return cid

        # Chunk the file
        estimated_chunks = estimate_chunk_count(file_size, chunk_size)
        logger.debug(f"Chunking file into ~{estimated_chunks} chunks")
        logger.info("=== Starting file chunking process ===")

        # leaf_triples: (cid_bytes, leaf_block_bytes, raw_data_size)
        leaf_triples: list[tuple[bytes, bytes, int]] = []
        bytes_processed = 0

        # Process file in chunks (memory efficient)
        for i, chunk_data in enumerate(chunk_file(file_path, chunk_size)):
            # Wrap chunk in UnixFS dag-pb leaf (matches Kubo's RawLeaves=false)
            leaf_block = create_leaf_node(chunk_data)
            chunk_cid = compute_cid_v1(leaf_block, codec=CODEC_DAG_PB)

            await self._put_block(chunk_cid, leaf_block)
            leaf_triples.append((chunk_cid, leaf_block, len(chunk_data)))
            bytes_processed += len(chunk_data)

            # Progress callback
            if progress_callback:
                await _call_progress_callback(
                    progress_callback,
                    bytes_processed,
                    file_size,
                    f"chunking ({i + 1} chunks)",
                )

            logger.info(
                f"Chunk {i + 1}: CID={format_cid_for_display(chunk_cid)}, "
                f"Size={len(chunk_data)} bytes, "
                f"Progress={bytes_processed}/{file_size}"
            )
            logger.debug(
                f"Stored leaf {i}: {format_cid_for_display(chunk_cid, max_len=16)} "
                f"({len(chunk_data)} bytes)"
            )

        # Build balanced DAG tree (max 174 links/node, matches Kubo)
        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "creating root node"
            )

        root_cid, root_data = balanced_layout(leaf_triples)
        await self._put_block(root_cid, root_data)

        # Enhanced logging for root CID
        logger.info("=== File chunking completed ===")
        logger.info(
            f"Root CID: {format_cid_for_display(root_cid)} "
            f"(Balanced DAG over {len(leaf_triples)} leaves)"
        )
        logger.info(f"Total file size: {file_size} bytes")
        logger.info("=" * 50)

        logger.info(
            f"Added file with {len(leaf_triples)} leaves. "
            f"Root CID: {format_cid_for_display(root_cid, max_len=16)}"
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
            await self._put_block(dir_cid, dir_data)

            logger.info(
                "Created directory wrapper. Directory CID: "
                f"{format_cid_for_display(dir_cid, max_len=16)}"
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

        # If data is small, store as single dag-pb leaf block
        if file_size <= chunk_size:
            leaf_block = create_leaf_node(data)
            cid = compute_cid_v1(leaf_block, codec=CODEC_DAG_PB)
            await self._put_block(cid, leaf_block)

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, file_size, file_size, "completed"
                )

            return cid

        # Chunk the data and wrap each chunk as a dag-pb leaf
        chunks = chunk_bytes(data, chunk_size)
        leaf_triples: list[tuple[bytes, bytes, int]] = []

        for i, chunk_data in enumerate(chunks):
            leaf_block = create_leaf_node(chunk_data)
            chunk_cid = compute_cid_v1(leaf_block, codec=CODEC_DAG_PB)
            await self._put_block(chunk_cid, leaf_block)
            leaf_triples.append((chunk_cid, leaf_block, len(chunk_data)))

            if progress_callback:
                bytes_processed = sum(s for _, _, s in leaf_triples)
                await _call_progress_callback(
                    progress_callback,
                    bytes_processed,
                    file_size,
                    f"chunking ({i + 1}/{len(chunks)})",
                )

        # Build balanced DAG tree
        root_cid, root_data = balanced_layout(leaf_triples)
        await self._put_block(root_cid, root_data)

        if progress_callback:
            await _call_progress_callback(
                progress_callback, file_size, file_size, "completed"
            )

        return root_cid

    async def fetch_file(
        self,
        root_cid: CIDInput,
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
        root_cid_bytes = cid_to_bytes(root_cid)
        logger.info(f"Fetching file: {format_cid_for_display(root_cid_bytes)}")

        # Step 1: Fetch the root block
        root_data = await self._get_block(root_cid_bytes, peer_id, timeout)
        if not verify_cid(root_cid_bytes, root_data):
            root_cid_str = format_cid_for_display(root_cid_bytes)
            raise ValueError(f"Root block CID verification failed: {root_cid_str}")

        # Step 2: Handle directory wrapper
        # (produced by `ipfs add --wrap-with-directory`)
        filename = None
        actual_file_cid = root_cid_bytes
        actual_file_data = root_data

        if is_directory_node(root_data):
            logger.info("Root is a directory node — extracting filename and file CID")
            dir_links, _ = decode_dag_pb(root_data)
            if dir_links:
                first_link = dir_links[0]
                filename = first_link.name or None
                actual_file_cid = first_link.cid
                logger.info(f"Filename from directory: {filename!r}")
                actual_file_data = await self._get_block(
                    actual_file_cid, peer_id, timeout
                )
                if not verify_cid(actual_file_cid, actual_file_data):
                    f_cid_str = format_cid_for_display(actual_file_cid)
                    err_msg = f"File block CID verification failed: {f_cid_str}"
                    raise ValueError(err_msg)

        # Step 3: Handle raw block (not a DAG-PB node at all)
        if not is_file_node(actual_file_data):
            logger.info(f"Root is a raw block: {len(actual_file_data)} bytes")
            return actual_file_data, filename

        # Step 4: Parse the file node
        top_links, top_unixfs = decode_dag_pb(actual_file_data)
        filesize = top_unixfs.filesize if top_unixfs else 0
        total_size = filesize or sum(lnk.size for lnk in top_links)
        msg = f"File node: {len(top_links)} top-level links, total size={total_size}"
        logger.info(f"{msg} bytes")

        # Step 5: Small file with inline data (no links)
        if not top_links:
            file_data = top_unixfs.data if top_unixfs and top_unixfs.data else b""
            logger.info(f"Inline file data: {len(file_data)} bytes")
            if progress_callback:
                data_len = len(file_data)
                await _call_progress_callback(
                    progress_callback, data_len, data_len, "completed"
                )
            return file_data, filename

        # Step 6: Collect all leaf CIDs without opening streams
        # Strategy: Recursively batch-fetch all DAG nodes
        # then traverse locally to collect leaves

        top_len = len(top_links)
        msg1 = f"[DAG] Recursively batch-fetching DAG tree ({top_len} top links)..."
        logger.info(msg1)
        msg2 = f"[FETCH] Recursively batch-fetching DAG tree ({top_len} top links)..."
        print(msg2, flush=True)

        # Map to store ALL fetched blocks (both intermediate and leaves)
        all_blocks_map: dict[bytes, bytes] = {}

        async def _batch_fetch_tree(cid_list: list[bytes], depth: int) -> None:
            """Recursively batch-fetch a level of DAG nodes and queue their children."""
            if not cid_list:
                return

            c_count = len(cid_list)
            msg1 = f"[DAG] Depth {depth}: batch-fetching {c_count} blocks..."
            logger.info(msg1)
            msg2 = f"[FETCH] Depth {depth}: batch-fetching {c_count} blocks..."
            print(msg2, flush=True)

            # Batch-fetch this level's blocks
            level_blocks = await self._get_blocks_batch(
                list(cid_list), peer_id=peer_id, timeout=timeout, batch_size=32
            )
            logger.info(f"[DAG] Depth {depth}: ✓ received {len(level_blocks)} blocks")
            all_blocks_map.update(level_blocks)

            # Collect child CIDs for recursion
            child_cids: list[bytes] = []
            for cid_bytes in cid_list:
                block_data = level_blocks.get(cid_bytes)
                if block_data is None:
                    c_str = format_cid_for_display(cid_bytes)
                    msg = f"[DAG] Depth {depth}: block {c_str} missing after"
                    logger.warning(f"{msg} fetch")
                    continue

                if is_file_node(block_data):
                    node_links, _ = decode_dag_pb(block_data)
                    cid_str = format_cid_for_display(cid_bytes)
                    msg = f"[DAG] Depth {depth}: {cid_str} has {len(node_links)}"
                    logger.debug(f"{msg} children")
                    for link in node_links:
                        child_cids.append(link.cid)

            # Recursively fetch next level if there are children
            if child_cids:
                ch_count = len(child_cids)
                msg = f"[DAG] Depth {depth}: found {ch_count} child CIDs"
                logger.info(f"{msg}, fetching next level...")
                await _batch_fetch_tree(child_cids, depth + 1)

        # Starting from the top-level links
        await _batch_fetch_tree([top_link.cid for top_link in top_links], depth=1)
        blocks_count = len(all_blocks_map)
        logger.info(f"[DAG] ✓ Tree fetch complete: {blocks_count} total blocks")
        print(f"[FETCH] ✓ Tree fetch complete: {blocks_count} total blocks", flush=True)

        # Now traverse locally to collect leaf CIDs in order
        ordered_leaf_cids: list[bytes] = []

        def _collect_leaves_local(cid_bytes: bytes, depth: int = 1) -> None:
            """Traverse locally-fetched blocks to collect leaf CIDs."""
            block_data = all_blocks_map.get(cid_bytes)
            if block_data is None:
                cid_str = format_cid_for_display(cid_bytes)
                logger.warning(f"[DAG] Depth {depth}: block {cid_str} not in map")
                return

            if not is_file_node(block_data):
                # Raw block - it's a leaf
                logger.debug(f"[DAG] Depth {depth}: raw block (leaf)")
                ordered_leaf_cids.append(cid_bytes)
                return

            node_links, _ = decode_dag_pb(block_data)
            logger.debug(f"[DAG] Depth {depth}: {len(node_links)} links")

            if not node_links:
                # Leaf node (no children, data is inline in UnixFS)
                logger.debug(f"[DAG] Depth {depth}: file node with inline data (leaf)")
                ordered_leaf_cids.append(cid_bytes)
                return

            # Intermediate node - recursively process children
            for j, child_link in enumerate(node_links):
                c_idx = j + 1
                c_tot = len(node_links)
                msg = f"[DAG] Depth {depth}: processing child {c_idx}/{c_tot}"
                logger.debug(msg)
                _collect_leaves_local(child_link.cid, depth + 1)

        # Traverse each top-level block
        for i, top_link in enumerate(top_links):
            logger.info(f"[DAG] Traversing top-level {i + 1}/{len(top_links)}...")
            _collect_leaves_local(top_link.cid, depth=1)

        logger.info(f"[DAG] ✓ Collected {len(ordered_leaf_cids)} leaf blocks")

        # Step 7: Batch-fetch all leaf blocks
        # (single wantlist per batch → avoids GO_AWAY)
        if progress_callback:
            await _call_progress_callback(
                progress_callback,
                0,
                total_size,
                f"fetching {len(ordered_leaf_cids)} leaf blocks in batches",
            )

        l_count = len(ordered_leaf_cids)
        msg1 = f"[DAG] Starting batch fetch of {l_count} leaves with batch_size=32"
        logger.info(f"{msg1}, timeout={timeout}s")
        msg2 = (
            f"[FETCH] Batch fetching {l_count} leaves "
            f"(batch_size=32, timeout={timeout}s)"
        )
        print(msg2, flush=True)
        block_map = await self._get_blocks_batch(
            list(ordered_leaf_cids), peer_id=peer_id, timeout=timeout, batch_size=32
        )
        logger.info(f"[DAG] ✓ Batch fetch complete: {len(block_map)} blocks received")
        print(f"[FETCH] ✓ Batch fetch complete: {len(block_map)} blocks", flush=True)

        # Step 8: Reassemble data in order
        # extracting UnixFS inline data from leaf nodes
        file_data = b""
        bytes_fetched = 0
        missing_blocks = []
        for idx, leaf_cid in enumerate(ordered_leaf_cids):
            leaf_raw = block_map.get(bytes(leaf_cid))
            if leaf_raw is None:
                l_idx = idx + 1
                t_leaves = len(ordered_leaf_cids)
                c_str = format_cid_for_display(leaf_cid)
                msg = f"[DAG] Leaf block {l_idx}/{t_leaves} MISSING: {c_str}"
                logger.error(msg)
                print(f"[FETCH] ✗ Leaf {l_idx}/{t_leaves} MISSING", flush=True)
                missing_blocks.append(leaf_cid)
                continue

            # Extract data: leaf blocks are UnixFS file nodes with inline data
            if is_file_node(leaf_raw):
                _, leaf_unixfs = decode_dag_pb(leaf_raw)
                if leaf_unixfs is not None and leaf_unixfs.data:
                    chunk = leaf_unixfs.data
                else:
                    chunk = b""
                chunk_len = len(chunk)
                msg = f"[DAG] Leaf {idx + 1}: extracted {chunk_len} bytes"
                logger.debug(f"{msg} from file node")
            else:
                chunk = leaf_raw
                logger.debug(f"[DAG] Leaf {idx + 1}: raw block {len(chunk)} bytes")

            file_data += chunk
            bytes_fetched += len(chunk)

            if (idx + 1) % 10 == 0 or idx == len(ordered_leaf_cids) - 1:
                i_p = idx + 1
                t_l = len(ordered_leaf_cids)
                p_str = f"{bytes_fetched}/{total_size} bytes"
                logger.info(f"[DAG] Reassembled {i_p}/{t_l} leaves: {p_str}")
                print(f"[FETCH] Reassembled {i_p}/{t_l} leaves: {p_str}", flush=True)

            if progress_callback:
                await _call_progress_callback(
                    progress_callback, bytes_fetched, total_size, "downloading"
                )

        if missing_blocks:
            missing_count = len(missing_blocks)
            logger.error(f"[DAG] ✗ {missing_count} blocks missing after batch fetch!")
            missing_list = [format_cid_for_display(cid) for cid in missing_blocks[:5]]
            msg = f"{missing_count} leaf blocks missing: {missing_list}..."
            raise BlockNotFoundError(msg)

        if progress_callback:
            await _call_progress_callback(
                progress_callback, total_size, total_size, "completed"
            )

        file_len = len(file_data)
        msg = f"[DAG] ✓ File fetch complete: {file_len} bytes, filename={filename!r}"
        logger.info(msg)
        print(f"[FETCH] ✓ DOWNLOAD COMPLETE: {file_len} bytes", flush=True)
        return file_data, filename

    async def get_file_info(
        self, root_cid: CIDInput, peer_id: PeerID | None = None, timeout: float = 30.0
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
        root_cid_bytes = cid_to_bytes(root_cid)
        root_data = await self._get_block(root_cid_bytes, peer_id, timeout)

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

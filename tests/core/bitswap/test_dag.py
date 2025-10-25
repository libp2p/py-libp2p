"""Integration tests for MerkleDag class."""

from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.chunker import DEFAULT_CHUNK_SIZE
from libp2p.bitswap.cid import CODEC_DAG_PB, CODEC_RAW, compute_cid_v1, verify_cid
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.dag import MerkleDag
from libp2p.bitswap.dag_pb import create_file_node, decode_dag_pb, is_file_node


class TestMerkleDagInit:
    """Test MerkleDag initialization."""

    def test_init_with_bitswap(self):
        """Test initializing with Bitswap client."""
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()

        dag = MerkleDag(mock_client)

        assert dag.bitswap is mock_client
        assert dag.block_store is mock_client.block_store

    def test_init_with_custom_store(self):
        """Test initializing with custom block store."""
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        custom_store = MemoryBlockStore()

        dag = MerkleDag(mock_client, block_store=custom_store)

        assert dag.bitswap is mock_client
        assert dag.block_store is custom_store
        assert dag.block_store is not mock_client.block_store


class TestAddBytes:
    """Test add_bytes method."""

    @pytest.mark.trio
    async def test_add_small_bytes(self):
        """Test adding small data (single block)."""
        # Setup
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.add_block = AsyncMock()

        dag = MerkleDag(mock_client)

        # Add small data
        data = b"hello world"
        root_cid = await dag.add_bytes(data)

        # Verify
        assert root_cid is not None
        assert len(root_cid) > 0
        assert verify_cid(root_cid, data)

        # Should be single block (RAW codec)
        mock_client.add_block.assert_called_once()
        call_args = mock_client.add_block.call_args
        assert call_args[0][0] == root_cid  # CID
        assert call_args[0][1] == data  # Data

    @pytest.mark.trio
    async def test_add_large_bytes(self):
        """Test adding large data (multiple chunks)."""
        # Setup
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.add_block = AsyncMock()

        dag = MerkleDag(mock_client)

        # Add large data (2 MB)
        data = b"x" * (2 * 1024 * 1024)
        root_cid = await dag.add_bytes(data, chunk_size=DEFAULT_CHUNK_SIZE)

        # Verify
        assert root_cid is not None

        # Should have multiple calls (chunks + root)
        assert mock_client.add_block.call_count > 1

        # Last call should be root node (DAG-PB)
        last_call = mock_client.add_block.call_args_list[-1]
        root_data = last_call[0][1]

        # Root should be a DAG-PB file node
        assert is_file_node(root_data)

        # Decode and verify structure
        links, unixfs_data = decode_dag_pb(root_data)
        assert len(links) > 0
        assert unixfs_data is not None
        assert unixfs_data.filesize == len(data)

    @pytest.mark.trio
    async def test_add_bytes_with_progress(self):
        """Test adding bytes with progress callback."""
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.add_block = AsyncMock()

        dag = MerkleDag(mock_client)

        progress_calls = []

        def progress_callback(current, total, status):
            progress_calls.append((current, total, status))

        # Add data with progress tracking
        data = b"y" * (1024 * 1024)  # 1 MB
        await dag.add_bytes(
            data, chunk_size=256 * 1024, progress_callback=progress_callback
        )

        # Verify progress was reported
        assert len(progress_calls) > 0
        # Last call should be completion
        assert progress_calls[-1][0] == progress_calls[-1][1]
        assert progress_calls[-1][2] == "completed"


class TestAddFile:
    """Test add_file method."""

    @pytest.mark.trio
    async def test_add_small_file(self):
        """Test adding small file."""
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            data = b"small file content"
            f.write(data)
            temp_path = f.name

        try:
            # Setup
            mock_client = MagicMock(spec=BitswapClient)
            mock_client.block_store = MemoryBlockStore()
            mock_client.add_block = AsyncMock()

            dag = MerkleDag(mock_client)

            # Add file (disable directory wrapping for this test)
            root_cid = await dag.add_file(temp_path, wrap_with_directory=False)

            # Verify
            assert root_cid is not None
            mock_client.add_block.assert_called_once()

            # Should be single RAW block
            call_args = mock_client.add_block.call_args
            assert verify_cid(call_args[0][0], data)
        finally:
            Path(temp_path).unlink()

    @pytest.mark.trio
    async def test_add_large_file(self):
        """Test adding large file."""
        # Create temp file (10 MB)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            file_size = 10 * 1024 * 1024
            # Write in chunks to avoid memory issues
            chunk = b"x" * (1024 * 1024)
            for _ in range(10):
                f.write(chunk)
            temp_path = f.name

        try:
            # Setup
            mock_client = MagicMock(spec=BitswapClient)
            mock_client.block_store = MemoryBlockStore()
            mock_client.add_block = AsyncMock()

            dag = MerkleDag(mock_client)

            # Add file (disable directory wrapping for this test)
            root_cid = await dag.add_file(temp_path, wrap_with_directory=False)

            # Verify
            assert root_cid is not None

            # Should have multiple blocks
            assert mock_client.add_block.call_count > 1

            # Root should be DAG-PB
            last_call = mock_client.add_block.call_args_list[-1]
            root_data = last_call[0][1]
            assert is_file_node(root_data)

            # Verify filesize
            links, unixfs_data = decode_dag_pb(root_data)
            assert unixfs_data is not None
            assert unixfs_data.filesize == file_size
        finally:
            Path(temp_path).unlink()

    @pytest.mark.trio
    async def test_add_file_not_found(self):
        """Test adding non-existent file."""
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()

        dag = MerkleDag(mock_client)

        with pytest.raises(FileNotFoundError):
            await dag.add_file("/nonexistent/file.txt")

    @pytest.mark.trio
    async def test_add_file_with_custom_chunk_size(self):
        """Test adding file with custom chunk size."""
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # 3.2 MB to divide evenly by 64KB
            data = b"x" * (3276800)  # 3.2 MB
            f.write(data)
            temp_path = f.name

        try:
            mock_client = MagicMock(spec=BitswapClient)
            mock_client.block_store = MemoryBlockStore()
            mock_client.add_block = AsyncMock()

            dag = MerkleDag(mock_client)

            # Add with smaller chunk size for testing (disable directory wrapping)
            chunk_size = 16 * 1024  # 16 KB for testing

            await dag.add_file(
                temp_path, chunk_size=chunk_size, wrap_with_directory=False
            )

            # Should have many chunks
            # (3.2MB / 16KB = 200 chunks) + 1 root = 201 calls
            assert mock_client.add_block.call_count == 201
        finally:
            Path(temp_path).unlink()


class TestFetchFile:
    """Test fetch_file method."""

    @pytest.mark.trio
    async def test_fetch_small_file(self):
        """Test fetching small single-block file."""
        # Original data
        data = b"test data"
        cid = compute_cid_v1(data, codec=CODEC_RAW)

        # Setup
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.get_block = AsyncMock(return_value=data)

        dag = MerkleDag(mock_client)

        # Fetch
        fetched_data, filename = await dag.fetch_file(cid, timeout=30.0)

        # Verify
        assert fetched_data == data
        assert filename is None  # Single RAW block doesn't have filename
        mock_client.get_block.assert_called_once_with(cid, None, 30.0)

    @pytest.mark.trio
    async def test_fetch_chunked_file(self):
        """Test fetching multi-chunk file."""
        # Create chunks
        chunk1 = b"chunk1" * 1000
        chunk2 = b"chunk2" * 1000
        chunk3 = b"chunk3" * 1000

        cid1 = compute_cid_v1(chunk1, codec=CODEC_RAW)
        cid2 = compute_cid_v1(chunk2, codec=CODEC_RAW)
        cid3 = compute_cid_v1(chunk3, codec=CODEC_RAW)

        # Create DAG-PB root node
        chunks_data = [
            (cid1, len(chunk1)),
            (cid2, len(chunk2)),
            (cid3, len(chunk3)),
        ]
        root_data = create_file_node(chunks_data)
        root_cid = compute_cid_v1(root_data, codec=CODEC_DAG_PB)

        # Setup mock to return blocks
        def get_block_side_effect(cid, peer_id, timeout):
            if cid == root_cid:
                return root_data
            elif cid == cid1:
                return chunk1
            elif cid == cid2:
                return chunk2
            elif cid == cid3:
                return chunk3
            raise ValueError(f"Unknown CID: {cid.hex()}")

        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.get_block = AsyncMock(side_effect=get_block_side_effect)

        dag = MerkleDag(mock_client)

        # Fetch
        fetched_data, filename = await dag.fetch_file(root_cid, timeout=30.0)

        # Verify
        expected_data = chunk1 + chunk2 + chunk3
        assert fetched_data == expected_data
        assert filename is None  # File node without directory wrapper

        # Should have fetched root + 3 chunks
        assert mock_client.get_block.call_count == 4

    @pytest.mark.trio
    async def test_fetch_file_with_progress(self):
        """Test fetching with progress callback."""
        # Create chunked file
        chunk1 = b"x" * 1000
        chunk2 = b"y" * 1000

        cid1 = compute_cid_v1(chunk1, codec=CODEC_RAW)
        cid2 = compute_cid_v1(chunk2, codec=CODEC_RAW)

        root_data = create_file_node([(cid1, len(chunk1)), (cid2, len(chunk2))])
        root_cid = compute_cid_v1(root_data, codec=CODEC_DAG_PB)

        # Setup
        def get_block_side_effect(cid, peer_id, timeout):
            if cid == root_cid:
                return root_data
            elif cid == cid1:
                return chunk1
            elif cid == cid2:
                return chunk2

        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.get_block = AsyncMock(side_effect=get_block_side_effect)

        dag = MerkleDag(mock_client)

        progress_calls = []

        def progress_callback(current, total, status):
            progress_calls.append((current, total, status))

        # Fetch
        await dag.fetch_file(root_cid, progress_callback=progress_callback)

        # Verify progress
        assert len(progress_calls) > 0
        # Should report progress for each chunk
        assert any("fetching chunk" in call[2] for call in progress_calls)
        # Last call should be completion
        assert progress_calls[-1][2] == "completed"


class TestGetFileInfo:
    """Test get_file_info method."""

    @pytest.mark.trio
    async def test_get_info_single_block(self):
        """Test getting info for single block."""
        data = b"test"
        cid = compute_cid_v1(data, codec=CODEC_RAW)

        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.get_block = AsyncMock(return_value=data)

        dag = MerkleDag(mock_client)

        info = await dag.get_file_info(cid)

        assert info["size"] == len(data)
        assert info["chunks"] == 1
        assert info["chunk_sizes"] == [len(data)]

    @pytest.mark.trio
    async def test_get_info_chunked_file(self):
        """Test getting info for chunked file."""
        # Create chunks
        chunks = [b"x" * 1000, b"y" * 2000, b"z" * 1500]
        cids = [compute_cid_v1(chunk, codec=CODEC_RAW) for chunk in chunks]

        chunks_data = [(cid, len(chunk)) for cid, chunk in zip(cids, chunks)]
        root_data = create_file_node(chunks_data)
        root_cid = compute_cid_v1(root_data, codec=CODEC_DAG_PB)

        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = MemoryBlockStore()
        mock_client.get_block = AsyncMock(return_value=root_data)

        dag = MerkleDag(mock_client)

        info = await dag.get_file_info(root_cid)

        assert info["size"] == sum(len(chunk) for chunk in chunks)
        assert info["chunks"] == 3
        assert info["chunk_sizes"] == [1000, 2000, 1500]


class TestEndToEnd:
    """End-to-end integration tests."""

    @pytest.mark.trio
    async def test_add_and_fetch_round_trip(self):
        """Test adding and fetching same file."""
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            original_data = b"round trip test data " * 10000
            f.write(original_data)
            temp_path = f.name

        try:
            # Setup with real store
            store = MemoryBlockStore()
            mock_client = MagicMock(spec=BitswapClient)
            mock_client.block_store = store

            # Capture blocks during add
            added_blocks = {}

            async def add_block_impl(cid, data):
                added_blocks[cid] = data
                await store.put_block(cid, data)

            mock_client.add_block = AsyncMock(side_effect=add_block_impl)

            # Return blocks during fetch
            async def get_block_impl(cid, peer_id, timeout):
                if cid in added_blocks:
                    return added_blocks[cid]
                raise KeyError(f"Block not found: {cid.hex()}")

            mock_client.get_block = AsyncMock(side_effect=get_block_impl)

            dag = MerkleDag(mock_client)

            # Add file (use smaller chunk size for testing, disable directory wrapping)
            chunk_size = 16 * 1024  # 16 KB for testing
            root_cid = await dag.add_file(
                temp_path,
                chunk_size=chunk_size,
                wrap_with_directory=False,
            )

            # Fetch file
            fetched_data, filename = await dag.fetch_file(root_cid, timeout=30.0)

            # Verify
            assert fetched_data == original_data
            assert filename is None  # No directory wrapping
        finally:
            Path(temp_path).unlink()

    @pytest.mark.trio
    async def test_add_bytes_and_fetch_round_trip(self):
        """Test adding and fetching bytes."""
        original_data = b"test data " * 100000  # ~1 MB

        # Setup
        store = MemoryBlockStore()
        mock_client = MagicMock(spec=BitswapClient)
        mock_client.block_store = store

        added_blocks = {}

        async def add_block_impl(cid, data):
            added_blocks[cid] = data

        async def get_block_impl(cid, peer_id, timeout):
            if cid in added_blocks:
                return added_blocks[cid]
            raise KeyError("Block not found")

        mock_client.add_block = AsyncMock(side_effect=add_block_impl)
        mock_client.get_block = AsyncMock(side_effect=get_block_impl)

        dag = MerkleDag(mock_client)

        # Add
        root_cid = await dag.add_bytes(original_data, chunk_size=256 * 1024)

        # Fetch
        fetched_data, filename = await dag.fetch_file(root_cid, timeout=30.0)

        # Verify
        assert fetched_data == original_data
        assert filename is None  # add_bytes doesn't create directory wrapper

    @pytest.mark.trio
    async def test_large_file_handling(self):
        """Test handling large file (50 MB)."""
        # Create large temp file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write 50 MB in 1 MB chunks
            chunk_data = b"x" * (1024 * 1024)
            for _ in range(50):
                f.write(chunk_data)
            temp_path = f.name
            file_size = 50 * 1024 * 1024

        try:
            # Setup
            store = MemoryBlockStore()
            mock_client = MagicMock(spec=BitswapClient)
            mock_client.block_store = store

            added_blocks = {}

            async def add_block_impl(cid, data):
                added_blocks[cid] = data

            async def get_block_impl(cid, peer_id, timeout):
                return added_blocks[cid]

            mock_client.add_block = AsyncMock(side_effect=add_block_impl)
            mock_client.get_block = AsyncMock(side_effect=get_block_impl)

            dag = MerkleDag(mock_client)

            progress_add = []
            progress_fetch = []

            def add_progress(current, total, status):
                progress_add.append((current, total, status))

            def fetch_progress(current, total, status):
                progress_fetch.append((current, total, status))

            # Add file (disable directory wrapping)
            root_cid = await dag.add_file(
                temp_path,
                chunk_size=1024 * 1024,
                progress_callback=add_progress,
                wrap_with_directory=False,
            )

            # Verify progress during add
            assert len(progress_add) > 0
            assert progress_add[-1][0] == file_size

            # Get info (should not fetch chunks)
            info = await dag.get_file_info(root_cid)
            assert info["size"] == file_size
            assert info["chunks"] == 50

            # Fetch file
            fetched_data, filename = await dag.fetch_file(
                root_cid, progress_callback=fetch_progress, timeout=30.0
            )

            # Verify
            assert len(fetched_data) == file_size
            assert len(progress_fetch) > 0
            assert filename is None  # No directory wrapping
        finally:
            Path(temp_path).unlink()

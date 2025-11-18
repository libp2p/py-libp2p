"""Unit tests for Bitswap client."""

from unittest.mock import MagicMock

import pytest

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import compute_cid_v1
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.config import (
    BITSWAP_PROTOCOL_V100,
    BITSWAP_PROTOCOL_V120,
)
from libp2p.bitswap.errors import TimeoutError as BitswapTimeoutError
from libp2p.peer.id import ID as PeerID


class TestBitswapClientInit:
    """Test BitswapClient initialization."""

    def test_init_default(self):
        """Test initializing with defaults."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        assert client.host is mock_host
        assert isinstance(client.block_store, MemoryBlockStore)
        assert client.protocol_version == BITSWAP_PROTOCOL_V120

    def test_init_with_block_store(self):
        """Test initializing with custom block store."""
        mock_host = MagicMock()
        custom_store = MemoryBlockStore()
        client = BitswapClient(mock_host, block_store=custom_store)

        assert client.block_store is custom_store

    def test_init_with_protocol_version(self):
        """Test initializing with specific protocol version."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host, protocol_version=BITSWAP_PROTOCOL_V100)

        assert client.protocol_version == BITSWAP_PROTOCOL_V100

    def test_init_state(self):
        """Test initial state of client."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        assert len(client._wantlist) == 0
        assert len(client._peer_wantlists) == 0
        assert len(client._pending_requests) == 0
        assert client._started is False


class TestBitswapClientStartStop:
    """Test client start/stop lifecycle."""

    @pytest.mark.trio
    async def test_start(self):
        """Test starting the client."""
        mock_host = MagicMock()
        mock_host.set_stream_handler = MagicMock()

        client = BitswapClient(mock_host)
        await client.start()

        assert client._started is True
        # Should register handlers for all protocols
        assert mock_host.set_stream_handler.call_count > 0

    @pytest.mark.trio
    async def test_start_idempotent(self):
        """Test starting multiple times is safe."""
        mock_host = MagicMock()
        mock_host.set_stream_handler = MagicMock()

        client = BitswapClient(mock_host)
        await client.start()
        call_count = mock_host.set_stream_handler.call_count

        # Start again
        await client.start()

        # Should not register handlers again
        assert mock_host.set_stream_handler.call_count == call_count

    @pytest.mark.trio
    async def test_stop(self):
        """Test stopping the client."""
        mock_host = MagicMock()
        mock_host.set_stream_handler = MagicMock()

        client = BitswapClient(mock_host)
        await client.start()
        await client.stop()

        assert client._started is False

    @pytest.mark.trio
    async def test_stop_without_start(self):
        """Test stopping without starting (should be safe)."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        # Should not raise
        await client.stop()


class TestBitswapClientWantlist:
    """Test wantlist management."""

    @pytest.mark.trio
    async def test_add_to_wantlist(self):
        """Test adding CID to wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        cid = compute_cid_v1(b"test data")

        await client.want_block(cid, priority=5)

        assert cid in client._wantlist
        assert client._wantlist[cid]["priority"] == 5

    @pytest.mark.trio
    async def test_remove_from_wantlist(self):
        """Test removing CID from wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        cid = compute_cid_v1(b"test data")

        await client.want_block(cid, priority=5)
        assert cid in client._wantlist

        await client.cancel_want(cid)
        assert cid not in client._wantlist

    @pytest.mark.trio
    async def test_has_in_wantlist(self):
        """Test checking if CID is in wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        cid = compute_cid_v1(b"test data")

        assert cid not in client._wantlist

        await client.want_block(cid)
        assert cid in client._wantlist


class TestBitswapClientBlockOperations:
    """Test block storage operations."""

    @pytest.mark.trio
    async def test_has_block(self):
        """Test checking if block exists."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        data = b"test data"
        cid = compute_cid_v1(data)

        # Should not have block initially
        has_block = await client.block_store.has_block(cid)
        assert has_block is False

        # Add block
        await client.block_store.put_block(cid, data)

        # Should have block now
        has_block = await client.block_store.has_block(cid)
        assert has_block is True

    @pytest.mark.trio
    async def test_get_block_local(self):
        """Test getting block from local store."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        data = b"test data"
        cid = compute_cid_v1(data)

        # Add block to store
        await client.block_store.put_block(cid, data)

        # Get block
        retrieved = await client.get_block(cid)
        assert retrieved == data

    @pytest.mark.trio
    async def test_put_block(self):
        """Test putting block into store."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        data = b"test data"
        cid = compute_cid_v1(data)

        # Put block (use add_block)
        await client.add_block(cid, data)

        # Verify it's in store
        has_block = await client.block_store.has_block(cid)
        assert has_block is True

        # Verify content
        retrieved = await client.block_store.get_block(cid)
        assert retrieved == data

    @pytest.mark.trio
    async def test_get_nonexistent_block(self):
        """Test getting block that doesn't exist locally."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        cid = compute_cid_v1(b"nonexistent")

        # Should timeout when block doesn't exist
        with pytest.raises(BitswapTimeoutError):
            await client.get_block(cid, timeout=0.1)


class TestBitswapClientPeerManagement:
    """Test peer management."""

    def test_track_peer_protocol(self):
        """Test tracking negotiated protocols per peer."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        peer_id = PeerID(b"peer123")
        protocol = BITSWAP_PROTOCOL_V120

        client._peer_protocols[peer_id] = protocol

        assert peer_id in client._peer_protocols
        assert client._peer_protocols[peer_id] == protocol

    def test_peer_wantlist(self):
        """Test tracking peer wantlists."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        peer_id = PeerID(b"peer123")
        cid_bytes = compute_cid_v1(b"data")

        client._peer_wantlists[peer_id] = {cid_bytes: {"priority": 1}}

        assert peer_id in client._peer_wantlists
        assert cid_bytes in client._peer_wantlists[peer_id]


class TestBitswapClientMultipleBlocks:
    """Test operations with multiple blocks."""

    @pytest.mark.trio
    async def test_put_multiple_blocks(self):
        """Test putting multiple blocks."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        blocks = {
            compute_cid_v1(b"data1"): b"data1",
            compute_cid_v1(b"data2"): b"data2",
            compute_cid_v1(b"data3"): b"data3",
        }

        # Put all blocks
        for cid, data in blocks.items():
            await client.add_block(cid, data)

        # Verify all blocks exist
        for cid, data in blocks.items():
            has_block = await client.block_store.has_block(cid)
            assert has_block is True
            retrieved = await client.get_block(cid)
            assert retrieved == data

    @pytest.mark.trio
    async def test_get_all_blocks(self):
        """Test getting all block CIDs."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        blocks = {
            compute_cid_v1(b"data1"): b"data1",
            compute_cid_v1(b"data2"): b"data2",
            compute_cid_v1(b"data3"): b"data3",
        }

        # Put all blocks
        for cid, data in blocks.items():
            await client.add_block(cid, data)

        # Get all CIDs
        all_cids = client.block_store.get_all_cids()

        assert len(all_cids) == len(blocks)
        for cid in blocks.keys():
            assert cid in all_cids

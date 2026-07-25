"""Unit tests for Bitswap client."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import cid_to_text, compute_cid_v1, parse_cid
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

        assert parse_cid(cid) in client._wantlist
        assert client._wantlist[parse_cid(cid)]["priority"] == 5

    @pytest.mark.trio
    async def test_remove_from_wantlist(self):
        """Test removing CID from wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        cid = compute_cid_v1(b"test data")

        await client.want_block(cid, priority=5)
        assert parse_cid(cid) in client._wantlist

        await client.cancel_want(cid)
        assert parse_cid(cid) not in client._wantlist

    @pytest.mark.trio
    async def test_has_in_wantlist(self):
        """Test checking if CID is in wantlist."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        cid = compute_cid_v1(b"test data")

        assert parse_cid(cid) not in client._wantlist

        await client.want_block(cid)
        assert parse_cid(cid) in client._wantlist


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
        retrieved = await client.new_session().get_block(cid)
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
            await client.new_session().get_block(cid, timeout=0.1)


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

        client._peer_wantlists[peer_id] = {parse_cid(cid_bytes): {"priority": 1}}

        assert peer_id in client._peer_wantlists
        assert parse_cid(cid_bytes) in client._peer_wantlists[peer_id]


class TestBitswapClientMixedCIDInputs:
    """Test public client APIs with mixed CID input types."""

    @pytest.mark.trio
    async def test_add_and_get_block_with_mixed_inputs(self):
        """Test add/get block APIs accept text, hex, and CID object forms."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        data = b"mixed-client-add-get"
        cid = compute_cid_v1(data)

        await client.add_block(cid_to_text(cid), data)
        assert await client.new_session().get_block(cid.hex()) == data
        assert await client.new_session().get_block(parse_cid(cid)) == data

    @pytest.mark.trio
    async def test_want_and_cancel_with_mixed_inputs(self):
        """Test want/cancel APIs normalize mixed input forms to one key."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"mixed-client-want-cancel")

        await client.want_block(cid_to_text(cid), priority=9)
        assert parse_cid(cid) in client._wantlist
        assert client._wantlist[parse_cid(cid)]["priority"] == 9

        await client.cancel_want(cid.hex())
        assert parse_cid(cid) not in client._wantlist

    @pytest.mark.trio
    async def test_have_block_with_canonical_text_input(self):
        """Test have_block accepts canonical text and uses normalized CID bytes."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"mixed-client-have")

        # Avoid network behavior and validate normalized bytes are propagated.
        client._broadcast_wantlist = AsyncMock()  # type: ignore[method-assign]
        await client.block_store.put_block(cid, b"mixed-client-have")

        has_block = await client.have_block(cid_to_text(cid))

        assert has_block is True
        assert parse_cid(cid) not in client._wantlist
        client._broadcast_wantlist.assert_awaited_once_with([parse_cid(cid)])  # type: ignore[attr-defined]


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
            retrieved = await client.new_session().get_block(cid)
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


class TestBitswapClientBugFixes:
    """Test regression fixes for critical Bitswap client bugs."""

    @pytest.mark.trio
    async def test_concurrent_get_block_same_cid(self, autojump_clock):
        """Test concurrent requests for the exact same CID don't race/orphan."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"concurrent_data")
        cid_obj = parse_cid(cid)
        client._send_wantlist_to_peer = AsyncMock(return_value=True)
        client._broadcast_wantlist = AsyncMock()

        results = []

        async def fetch_block():
            data = await client.new_session().get_block(cid, timeout=2.0)
            results.append(data)

        async def mock_network_delivery():
            await trio.sleep(0.5)
            await client.add_block(cid_obj, b"concurrent_data")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(mock_network_delivery)
            for _ in range(5):
                nursery.start_soon(fetch_block)

        assert len(results) == 5
        assert all(r == b"concurrent_data" for r in results)

    @pytest.mark.trio
    async def test_add_block_invalid_cid(self):
        """Test CID validation prevents corrupt data (Bug 7)."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"real_data")

        with pytest.raises(ValueError, match="Block data does not match CID hash"):
            await client.add_block(cid, b"fake_data")

    @pytest.mark.trio
    async def test_timeout_cleanup(self, autojump_clock):
        """Test timeout properly cleans up dictionaries (Bugs 5 & 9)."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"missing_data")
        cid_obj = parse_cid(cid)
        client._send_wantlist_to_peer = AsyncMock(return_value=True)
        client._broadcast_wantlist = AsyncMock()

        # Simulate expected block setup and dont_have
        peer_id = PeerID(b"peer1")
        client.presence_manager.add_have(peer_id, cid_obj)
        client.presence_manager.add_dont_have(peer_id, cid_obj)

        with pytest.raises(BitswapTimeoutError):
            await client.new_session().get_block(cid, timeout=0.1)

        assert cid_obj not in client._wantlist
        assert peer_id not in client.presence_manager.get_dont_have_peers(cid_obj)
        expected_cids = client.presence_manager.get_expected_cids_for_peer(peer_id)
        assert cid_obj not in expected_cids

    @pytest.mark.trio
    async def test_broadcast_limit(self):
        """Test wantlist broadcast is limited to max 20 peers (Bug 6)."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)

        # Mock 50 connected peers
        mock_connections = {PeerID(f"peer{i}".encode()): MagicMock() for i in range(50)}
        mock_host.get_network().connections = mock_connections

        client._send_wantlist_to_peer = AsyncMock(return_value=True)

        cid = compute_cid_v1(b"broadcast_data")
        await client._broadcast_wantlist([cid])

        assert client._send_wantlist_to_peer.call_count == 20

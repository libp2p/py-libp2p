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
        """Test have_block accepts canonical text and returns True for local blocks."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        cid = compute_cid_v1(b"mixed-client-have")

        # Put block locally — have_block should return True immediately
        client._broadcast_wantlist = AsyncMock()  # type: ignore[method-assign]
        await client.block_store.put_block(cid, b"mixed-client-have")

        has_block = await client.have_block(cid_to_text(cid))

        assert has_block is True
        # Block was local, so no network broadcast needed
        client._broadcast_wantlist.assert_not_awaited()


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


class TestBitswapClientPerStreamReader:
    """
    Regression tests for per-stream expected-block tracking.

    The response reader used to watch the *peer-global* expected set, so a
    stream opened for one batch would (a) stay open until the whole transfer
    finished and (b) report CIDs owned by other concurrent streams as
    missing, both of which broke large multi-batch transfers.
    """

    class FakeStream:
        """Minimal INetStream stand-in: EOF on read, records close."""

        def __init__(self):
            self.closed = False

        async def read(self, n):
            return b""

        async def close(self):
            self.closed = True

    @pytest.mark.trio
    async def test_reader_does_not_disturb_other_streams_cids(self):
        """
        When a stream dies, the reader must not remove CIDs from the peer's
        expected set — the session owns that cleanup, and removing entries
        would break concurrent streams' accounting (the pre-fix behavior
        removed the whole peer-global set).
        """
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        peer_id = PeerID(b"peer-stream-scope")

        c1 = parse_cid(compute_cid_v1(b"block-one"))
        c2 = parse_cid(compute_cid_v1(b"block-two"))

        # Both CIDs are expected from the peer; this stream only asked for c1.
        client.presence_manager.add_have(peer_id, c1)
        client.presence_manager.add_have(peer_id, c2)

        stream = self.FakeStream()
        await client._read_responses_from_stream(stream, peer_id, [c1])  # type: ignore[arg-type]  # noqa: E501  # test double

        # Neither c1 nor c2 may be dropped by this stream's cleanup.
        expected = client.presence_manager.get_expected_for_peer(peer_id)
        assert c1 in expected
        assert c2 in expected
        assert stream.closed

    @pytest.mark.trio
    async def test_reader_exits_when_own_cids_received(self):
        """
        A reader exits immediately once all of *its own* CIDs are received,
        even while other CIDs remain pending for the same peer.
        """
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        peer_id = PeerID(b"peer-stream-scope2")

        c1 = parse_cid(compute_cid_v1(b"block-one"))
        c2 = parse_cid(compute_cid_v1(b"block-two"))

        # c1 was already delivered (not expected anymore); c2 is still pending
        # for the peer but belongs to a different stream.
        client.presence_manager.add_have(peer_id, c2)

        stream = self.FakeStream()
        await client._read_responses_from_stream(stream, peer_id, [c1])  # type: ignore[arg-type]  # noqa: E501  # test double

        assert stream.closed
        # c2 must not be touched by this stream's cleanup.
        expected = client.presence_manager.get_expected_for_peer(peer_id)
        assert c2 in expected


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
        from libp2p.bitswap.cid import parse_cid

        cid_obj = parse_cid(cid)
        await client._broadcast_wantlist([cid_obj])

        assert client._send_wantlist_to_peer.call_count == 20


class TestBitswapClientPeerCleanup:
    """
    Per-peer state must be reaped on disconnect so long-running nodes don't
    accumulate wantlists, protocols, presence and stats for every peer they
    have ever talked to.
    """

    def _populate_peer_state(self, client, peer_id):
        cid_obj = parse_cid(compute_cid_v1(b"leak-test"))
        client._peer_wantlists[peer_id] = {
            cid_obj: {"priority": 1, "want_type": 0, "send_dont_have": False}
        }
        client._peer_protocols[peer_id] = BITSWAP_PROTOCOL_V120
        client._peer_pending_bytes[peer_id] = 1234
        client.peer_manager._get_stats(peer_id).requests_sent = 5
        client.presence_manager.add_have(peer_id, cid_obj)
        client.presence_manager.add_dont_have(cid_obj, peer_id)
        return cid_obj

    def test_cleanup_peer_removes_all_per_peer_state(self):
        """cleanup_peer drops every per-peer structure for that peer."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        peer_id = PeerID(b"peer-leak-1")
        cid_obj = self._populate_peer_state(client, peer_id)

        client.cleanup_peer(peer_id)

        assert peer_id not in client._peer_wantlists
        assert peer_id not in client._peer_protocols
        assert peer_id not in client._peer_pending_bytes
        assert peer_id not in client.peer_manager.peers
        assert peer_id not in client.presence_manager._have
        # dont_have entries keyed by this peer are dropped too
        assert cid_obj not in client.presence_manager._dont_have

    def test_cleanup_peer_idempotent(self):
        """cleanup_peer is safe for peers with no recorded state."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        client.cleanup_peer(PeerID(b"peer-never-seen"))

    @pytest.mark.trio
    async def test_disconnected_notifee_cleans_peer_state(self):
        """The INotifee.disconnected hook reaps the disconnected peer's state."""
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        peer_id = PeerID(b"peer-leak-2")
        self._populate_peer_state(client, peer_id)

        conn = MagicMock()
        conn.muxed_conn.peer_id = peer_id
        await client.disconnected(None, conn)

        assert peer_id not in client._peer_wantlists
        assert peer_id not in client._peer_protocols
        assert peer_id not in client.peer_manager.peers

    @pytest.mark.trio
    async def test_start_registers_notifee_and_stop_unregisters(self):
        """The client registers as a network notifee on start and removes it on stop."""
        mock_host = MagicMock()
        mock_net = MagicMock()
        mock_host.get_network.return_value = mock_net

        client = BitswapClient(mock_host)
        await client.start()
        mock_net.register_notifee.assert_called_once_with(client)
        assert client._notifee_registered is True

        await client.stop()
        mock_net.remove_notifee.assert_called_once_with(client)
        assert client._notifee_registered is False

    @pytest.mark.trio
    async def test_disconnected_only_cleans_after_last_connection(self):
        """
        Per-peer state is kept while the peer still has other connections open
        and only reaped once the last connection closes.
        """
        mock_host = MagicMock()
        mock_net = MagicMock()
        mock_host.get_network.return_value = mock_net
        client = BitswapClient(mock_host)
        peer_id = PeerID(b"peer-leak-3")
        self._populate_peer_state(client, peer_id)

        conn = MagicMock()
        conn.muxed_conn.peer_id = peer_id

        # One connection to the peer still remains -> state must survive.
        mock_net.get_connections.return_value = [MagicMock()]
        await client.disconnected(mock_net, conn)
        assert peer_id in client._peer_wantlists
        assert peer_id in client.peer_manager.peers

        # Last connection closed -> state is reaped.
        mock_net.get_connections.return_value = []
        await client.disconnected(mock_net, conn)
        assert peer_id not in client._peer_wantlists
        assert peer_id not in client.peer_manager.peers

    @pytest.mark.trio
    async def test_set_nursery_starts_presence_cleanup_loop_when_started(self):
        """
        set_nursery() called after start() launches the presence-cleanup loop
        (previously the loop silently never ran when the nursery was attached
        after start).
        """
        mock_host = MagicMock()
        client = BitswapClient(mock_host)
        await client.start()
        assert client._presence_cleanup_started is False

        async with trio.open_nursery() as nursery:
            client.set_nursery(nursery)
            assert client._presence_cleanup_started is True
            # Let the loop spin up; stop() (as in production shutdown) must
            # terminate it so the nursery can exit promptly.
            await trio.sleep(0.2)
            await client.stop()
            assert client._presence_cleanup_started is False

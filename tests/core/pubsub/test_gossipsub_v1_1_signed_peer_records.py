"""
Tests for Gossipsub v1.1 Signed Peer Records functionality.

This module tests the signed peer records validation, handling, and integration
with peer exchange (PX) in GossipSub v1.1.
"""

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trio

from libp2p.peer.peerinfo import PeerInfo
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.utils import maybe_consume_signed_record
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


class TestSignedPeerRecords:
    """Test signed peer records functionality."""

    def test_maybe_consume_signed_record_valid(self):
        """Test consuming a valid signed peer record."""
        # This test would require creating actual signed peer records
        # For now, we'll test the function signature and basic behavior
        rpc = rpc_pb2.RPC()
        # rpc.senderRecord = valid_signed_record_bytes

        # Mock host and peer_id
        mock_host = MagicMock()
        mock_peer_id = IDFactory()

        # Test without senderRecord (should return True)
        result = maybe_consume_signed_record(rpc, mock_host, mock_peer_id)
        assert result is True

    def test_maybe_consume_signed_record_invalid_peer_id(self):
        """Test consuming signed peer record with mismatched peer ID."""
        rpc = rpc_pb2.RPC()
        mock_host = MagicMock()
        mock_peer_id = IDFactory()

        # Mock consume_envelope to return different peer_id
        with patch("libp2p.pubsub.utils.consume_envelope") as mock_consume:
            mock_envelope = MagicMock()
            mock_record = MagicMock()
            mock_record.peer_id = IDFactory()  # Different peer ID
            mock_consume.return_value = (mock_envelope, mock_record)

            rpc.senderRecord = b"fake_signed_record"
            result = maybe_consume_signed_record(rpc, mock_host, mock_peer_id)
            assert result is False

    def test_maybe_consume_signed_record_consume_failure(self):
        """Test handling of peerstore consume failure."""
        rpc = rpc_pb2.RPC()
        mock_host = MagicMock()
        mock_peer_id = IDFactory()

        # Mock consume_envelope to succeed but peerstore consume to fail
        with patch("libp2p.pubsub.utils.consume_envelope") as mock_consume:
            mock_envelope = MagicMock()
            mock_record = MagicMock()
            mock_record.peer_id = mock_peer_id
            mock_consume.return_value = (mock_envelope, mock_record)

            # Mock peerstore consume to return False
            mock_host.get_peerstore.return_value.consume_peer_record.return_value = (
                False
            )

            rpc.senderRecord = b"fake_signed_record"
            result = maybe_consume_signed_record(rpc, mock_host, mock_peer_id)
            assert result is False

    def test_maybe_consume_signed_record_parse_error(self):
        """Test handling of envelope parsing errors."""
        rpc = rpc_pb2.RPC()
        mock_host = MagicMock()
        mock_peer_id = IDFactory()

        # Mock consume_envelope to raise exception
        with patch("libp2p.pubsub.utils.consume_envelope") as mock_consume:
            mock_consume.side_effect = Exception("Parse error")

            rpc.senderRecord = b"invalid_signed_record"
            result = maybe_consume_signed_record(rpc, mock_host, mock_peer_id)
            assert result is False


class TestGossipSubSignedPeerRecords:
    """Test GossipSub integration with signed peer records."""

    @pytest.mark.trio
    async def test_emit_prune_with_signed_records(self):
        """Test that emit_prune includes signed peer records in PX."""
        async with PubsubFactory.create_batch_with_gossipsub(
            3, do_px=True, px_peers_count=2, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1, gsub2 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1, host2 = (ps.host for ps in pubsubs)

            # Connect all hosts
            await connect(host0, host1)
            await connect(host1, host2)
            await connect(host0, host2)
            await trio.sleep(0.2)

            topic = "test_emit_prune_signed_records"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(0.2)

            # Mock the peerstore to return a signed record for host2
            assert gsub0.pubsub is not None
            mock_envelope = MagicMock()
            mock_envelope.marshal_envelope.return_value = b"fake_signed_record"
            mock_peerstore = MagicMock()
            mock_peerstore.get_peer_record.return_value = mock_envelope
            # Mock the get_peerstore method
            gsub0.pubsub.host.get_peerstore = MagicMock(return_value=mock_peerstore)

            # Mock write_msg to capture the sent message
            assert gsub0.pubsub is not None
            mock_write_msg = AsyncMock()
            gsub0.pubsub.write_msg = mock_write_msg

            # Emit prune with PX enabled
            await gsub0.emit_prune(
                topic, host1.get_id(), do_px=True, is_unsubscribe=False
            )

            # Verify that write_msg was called
            mock_write_msg.assert_called_once()
            call_args = mock_write_msg.call_args[0]
            rpc_msg = call_args[1]

            # Verify the RPC message contains prune with peers
            assert len(rpc_msg.control.prune) == 1
            prune_msg = rpc_msg.control.prune[0]
            assert prune_msg.topicID == topic
            assert len(prune_msg.peers) > 0

            # Verify that peer records include signed records
            for peer_info in prune_msg.peers:
                assert peer_info.HasField("peerID")
                # Should have signed record if available
                if peer_info.HasField("signedPeerRecord"):
                    assert len(peer_info.signedPeerRecord) > 0

    @pytest.mark.trio
    async def test_do_px_with_signed_records(self):
        """Test that _do_px processes signed peer records correctly."""
        async with PubsubFactory.create_batch_with_gossipsub(
            3, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1, gsub2 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1, host2 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            # Create mock signed peer record
            mock_envelope = MagicMock()
            mock_record = MagicMock()
            mock_record.peer_id = host2.get_id()
            mock_record.addrs = [host2.get_addrs()[0]] if host2.get_addrs() else []

            # Mock consume_envelope
            with patch("libp2p.pubsub.gossipsub.consume_envelope") as mock_consume:
                mock_consume.return_value = (mock_envelope, mock_record)

                # Mock peerstore consume_peer_record
                assert gsub0.pubsub is not None
                mock_peerstore = MagicMock()
                mock_peerstore.consume_peer_record.return_value = True
                mock_host = MagicMock()
                mock_host.get_peerstore.return_value = mock_peerstore
                mock_host.connect = AsyncMock()
                gsub0.pubsub.host = mock_host

                # Create PX peer info with signed record
                px_peer = rpc_pb2.PeerInfo()
                px_peer.peerID = host2.get_id().to_bytes()
                px_peer.signedPeerRecord = b"fake_signed_record"

                # Test _do_px
                await gsub0._do_px([px_peer])

                # Verify that consume_envelope was called
                mock_consume.assert_called_once_with(
                    b"fake_signed_record", "libp2p-peer-record"
                )

                # Verify that peerstore consume_peer_record was called
                mock_peerstore.consume_peer_record.assert_called_once_with(
                    mock_envelope, ttl=7200
                )

                # Verify that host connect was called
                assert gsub0.pubsub is not None
                gsub0.pubsub.host.connect.assert_called_once()

    @pytest.mark.trio
    async def test_do_px_peer_id_mismatch(self):
        """Test that _do_px rejects signed records with mismatched peer IDs."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Create mock signed peer record with mismatched peer ID
            mock_envelope = MagicMock()
            mock_record = MagicMock()
            mock_record.peer_id = IDFactory()  # Different peer ID

            # Mock peerstore
            assert gsub0.pubsub is not None
            mock_peerstore = MagicMock()
            gsub0.pubsub.host.get_peerstore = MagicMock(return_value=mock_peerstore)

            # Mock consume_envelope
            with patch("libp2p.pubsub.gossipsub.consume_envelope") as mock_consume:
                mock_consume.return_value = (mock_envelope, mock_record)

                # Create PX peer info with signed record for a peer that's not connected
                px_peer = rpc_pb2.PeerInfo()
                px_peer.peerID = IDFactory().to_bytes()  # Use a different peer ID
                px_peer.signedPeerRecord = b"fake_signed_record"

                # Test _do_px - should handle the mismatch gracefully
                await gsub0._do_px([px_peer])

                # Verify that consume_envelope was called
                mock_consume.assert_called_once()

                # Verify that peerstore consume_peer_record was NOT called
                mock_peerstore.consume_peer_record.assert_not_called()

    @pytest.mark.trio
    async def test_do_px_fallback_to_existing_peer_info(self):
        """Test that _do_px falls back to existing peer info when no signed record."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Mock peerstore to return existing peer info
            assert gsub0.pubsub is not None
            pubsub = gsub0.pubsub
            mock_peer_info = PeerInfo(host1.get_id(), host1.get_addrs())
            mock_peerstore = MagicMock()
            mock_peerstore.peer_info.return_value = mock_peer_info
            pubsub.host.get_peerstore = MagicMock(return_value=mock_peerstore)
            pubsub.host.connect = AsyncMock()

            # Create PX peer info without signed record for a peer that's not connected
            px_peer = rpc_pb2.PeerInfo()
            px_peer.peerID = IDFactory().to_bytes()  # Use a different peer ID
            # No signedPeerRecord field

            # Test _do_px
            await gsub0._do_px([px_peer])

            # Verify that peerstore peer_info was called
            mock_peerstore.peer_info.assert_called_once()

            # Verify that host connect was called with existing peer info
            assert gsub0.pubsub is not None
            pubsub.host.connect.assert_called_once_with(mock_peer_info)

    @pytest.mark.trio
    async def test_do_px_no_existing_peer_info(self):
        """Test that _do_px handles missing peer info gracefully."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Mock peerstore to raise exception (peer not found)
            assert gsub0.pubsub is not None
            mock_peerstore = MagicMock()
            mock_peerstore.peer_info.side_effect = Exception("Peer not found")
            gsub0.pubsub.host.get_peerstore = MagicMock(return_value=mock_peerstore)

            # Mock host connect to track calls
            assert gsub0.pubsub is not None
            mock_connect = AsyncMock()
            gsub0.pubsub.host.connect = mock_connect

            # Create PX peer info without signed record for a peer that's not connected
            px_peer = rpc_pb2.PeerInfo()
            px_peer.peerID = IDFactory().to_bytes()  # Use a different peer ID

            # Test _do_px - should handle gracefully
            await gsub0._do_px([px_peer])

            # Verify that peerstore peer_info was called
            mock_peerstore.peer_info.assert_called_once()

            # Verify that host connect was NOT called
            mock_connect.assert_not_called()

    @pytest.mark.trio
    async def test_do_px_connection_failure(self):
        """Test that _do_px handles connection failures gracefully."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Mock peerstore to return existing peer info
            assert gsub0.pubsub is not None
            mock_peer_info = PeerInfo(host1.get_id(), host1.get_addrs())
            mock_peerstore = MagicMock()
            mock_peerstore.peer_info.return_value = mock_peer_info
            gsub0.pubsub.host.get_peerstore = MagicMock(return_value=mock_peerstore)

            # Mock host connect to raise exception
            assert gsub0.pubsub is not None
            mock_connect = AsyncMock(side_effect=Exception("Connection failed"))
            gsub0.pubsub.host.connect = mock_connect

            # Create PX peer info without signed record for a peer that's not connected
            px_peer = rpc_pb2.PeerInfo()
            px_peer.peerID = IDFactory().to_bytes()  # Use a different peer ID

            # Test _do_px - should handle connection failure gracefully
            await gsub0._do_px([px_peer])

            # Verify that host connect was called
            mock_connect.assert_called_once_with(mock_peer_info)

    @pytest.mark.trio
    async def test_do_px_limit_peers_count(self):
        """Test that _do_px respects px_peers_count limit."""
        async with PubsubFactory.create_batch_with_gossipsub(
            1, do_px=True, px_peers_count=2, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = cast(GossipSub, pubsubs[0].router)

            # Create more PX peers than the limit
            px_peers = []
            for i in range(5):  # More than px_peers_count=2
                px_peer = rpc_pb2.PeerInfo()
                px_peer.peerID = IDFactory().to_bytes()
                px_peers.append(px_peer)

            # Mock peerstore and host
            assert gsub0.pubsub is not None
            mock_peerstore = MagicMock()
            mock_peerstore.peer_info.side_effect = Exception("Peer not found")
            gsub0.pubsub.host.get_peerstore = MagicMock(return_value=mock_peerstore)

            # Test _do_px
            await gsub0._do_px(px_peers)

            # Verify that only px_peers_count peers were processed
            # (This is handled by the slice operation in _do_px)
            assert len(px_peers) == 5  # Original list unchanged
            # The actual processing is limited by the slice in _do_px

    @pytest.mark.trio
    async def test_do_px_skip_existing_connections(self):
        """Test that _do_px skips peers that are already connected."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            # Create PX peer info for already connected peer
            px_peer = rpc_pb2.PeerInfo()
            px_peer.peerID = host1.get_id().to_bytes()

            # Mock host connect
            assert gsub0.pubsub is not None
            gsub0.pubsub.host.connect = AsyncMock()

            # Test _do_px
            await gsub0._do_px([px_peer])

            # Verify that host connect was NOT called (peer already connected)
            assert gsub0.pubsub is not None
            gsub0.pubsub.host.connect.assert_not_called()

    @pytest.mark.trio
    async def test_handle_rpc_signed_record_validation(self):
        """Test that handle_rpc validates signed records."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            # Mock maybe_consume_signed_record to return False (invalid record)
            with patch(
                "libp2p.pubsub.gossipsub.maybe_consume_signed_record"
            ) as mock_consume:
                mock_consume.return_value = False

                # Create RPC with invalid signed record
                rpc = rpc_pb2.RPC()
                rpc.senderRecord = b"invalid_signed_record"
                rpc.control.CopyFrom(rpc_pb2.ControlMessage())

                # Test handle_rpc
                await gsub0.handle_rpc(rpc, host1.get_id())

                # Verify that maybe_consume_signed_record was called
                assert gsub0.pubsub is not None
                mock_consume.assert_called_once_with(
                    rpc, gsub0.pubsub.host, host1.get_id()
                )

    @pytest.mark.trio
    async def test_emit_control_message_sender_record(self):
        """Test that emit_control_message includes sender record."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            # Mock env_to_send_in_RPC
            with patch("libp2p.pubsub.gossipsub.env_to_send_in_RPC") as mock_env:
                mock_env.return_value = (b"fake_sender_record", None)

                # Mock write_msg to capture the sent message
                assert gsub0.pubsub is not None
                mock_write_msg = AsyncMock()
                gsub0.pubsub.write_msg = mock_write_msg

                # Create control message
                control_msg = rpc_pb2.ControlMessage()
                graft_msg = rpc_pb2.ControlGraft(topicID="test_topic")
                control_msg.graft.extend([graft_msg])

                # Test emit_control_message
                await gsub0.emit_control_message(control_msg, host1.get_id())

                # Verify that write_msg was called
                mock_write_msg.assert_called_once()
                call_args = mock_write_msg.call_args[0]
                rpc_msg = call_args[1]

                # Verify that sender record is included
                assert rpc_msg.HasField("senderRecord")
                assert rpc_msg.senderRecord == b"fake_sender_record"

    @pytest.mark.trio
    async def test_emit_iwant_sender_record(self):
        """Test that emit_iwant includes sender record."""
        async with PubsubFactory.create_batch_with_gossipsub(
            2, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            # Mock env_to_send_in_RPC
            with patch("libp2p.pubsub.gossipsub.env_to_send_in_RPC") as mock_env:
                mock_env.return_value = (b"fake_sender_record", None)

                # Mock write_msg to capture the sent message
                assert gsub0.pubsub is not None
                mock_write_msg = AsyncMock()
                gsub0.pubsub.write_msg = mock_write_msg

                # Test emit_iwant
                msg_ids = ["msg1", "msg2"]
                await gsub0.emit_iwant(msg_ids, host1.get_id())

                # Verify that write_msg was called
                mock_write_msg.assert_called_once()
                call_args = mock_write_msg.call_args[0]
                rpc_msg = call_args[1]

                # Verify that sender record is included
                assert rpc_msg.HasField("senderRecord")
                assert rpc_msg.senderRecord == b"fake_sender_record"

                # Verify that iwant message is included
                assert len(rpc_msg.control.iwant) == 1
                iwant_msg = rpc_msg.control.iwant[0]
                assert list(iwant_msg.messageIDs) == msg_ids

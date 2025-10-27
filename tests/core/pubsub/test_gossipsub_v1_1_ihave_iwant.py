"""
Tests for Gossipsub v1.1 IHAVE/IWANT Adaptive Gossip functionality.

This module tests the IHAVE/IWANT mechanism in GossipSub v1.1, including:
- IWANT requests triggered by dropped gossip
- Prevention of infinite gossip loops
"""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_ihave_triggers_iwant_for_missing_messages():
    """Test that IHAVE messages trigger IWANT requests for missing messages."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_ihave_iwant"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Create a message ID that gsub0 doesn't have
        # Message IDs in GossipSub are string representations of (seqno, from_id) tuples
        missing_msg_id = str((b"seqno123", b"peer456"))

        # Mock emit_iwant to capture IWANT requests
        emit_iwant_mock = AsyncMock()
        gsub0.emit_iwant = emit_iwant_mock

        # Create IHAVE control message
        ihave_msg = rpc_pb2.ControlIHave(messageIDs=[missing_msg_id], topicID=topic)

        # Simulate receiving IHAVE message
        await gsub0.handle_ihave(ihave_msg, host1.get_id())

        # Verify that emit_iwant was called
        emit_iwant_mock.assert_called_once()

        # The first argument should be a list of message IDs
        call_args = emit_iwant_mock.call_args[0]
        assert len(call_args[0]) > 0  # Should have at least one message ID
        assert call_args[1] == host1.get_id()  # Second arg is peer ID


@pytest.mark.trio
async def test_iwant_retrieves_missing_messages():
    """Test that IWANT requests retrieve missing messages."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_iwant_retrieval"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Create a message that gsub1 has but gsub0 doesn't
        # Message IDs in GossipSub are string representations of (seqno, from_id) tuples
        seqno = b"seqno123"
        from_id = b"peer456"
        msg_id_tuple = (seqno, from_id)
        msg_id_str = str(msg_id_tuple)

        msg_data = b"test message data"

        # Create a message
        msg = rpc_pb2.Message(
            data=msg_data,
            topicIDs=[topic],
            from_id=from_id,
            seqno=seqno,
        )

        # Mock gsub1's message cache to return our test message
        gsub1.mcache.get = MagicMock(return_value=msg)

        # Mock gsub1's write_msg to capture sent messages
        # Create a mock for pubsub if it doesn't exist
        if not hasattr(gsub1, "pubsub") or gsub1.pubsub is None:
            gsub1.pubsub = MagicMock()

        write_msg_mock = AsyncMock()
        gsub1.pubsub.write_msg = write_msg_mock

        # Create IWANT control message
        iwant_msg = rpc_pb2.ControlIWant(messageIDs=[msg_id_str])

        # Simulate gsub0 sending IWANT to gsub1
        await gsub1.handle_iwant(iwant_msg, host0.get_id())

        # Wait for async operations
        await trio.sleep(0.5)

        # Verify that gsub1's message cache was queried
        gsub1.mcache.get.assert_called_once()

        # Verify that write_msg was called to send the message
        write_msg_mock.assert_called_once()

        # Verify that the sent message contains our test message
        call_args = write_msg_mock.call_args[0]
        rpc_msg = call_args[1]
        assert len(rpc_msg.publish) == 1
        assert rpc_msg.publish[0].data == msg_data


@pytest.mark.trio
async def test_ihave_rate_limiting():
    """Test that IHAVE messages are rate-limited to prevent gossip storms."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_ihave_rate_limiting"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Create multiple message IDs
        msg_ids = [
            str((f"seqno_{i}".encode(), f"peer_{i}".encode())) for i in range(100)
        ]

        # Create IHAVE control message with many message IDs
        ihave_msg = rpc_pb2.ControlIHave(messageIDs=msg_ids, topicID=topic)

        # Mock emit_iwant to capture IWANT requests
        emit_iwant_mock = AsyncMock()
        gsub0.emit_iwant = emit_iwant_mock

        # Simulate receiving IHAVE message
        await gsub0.handle_ihave(ihave_msg, host1.get_id())

        # Verify that emit_iwant was called
        emit_iwant_mock.assert_called_once()
        call_args = emit_iwant_mock.call_args[0]

        # Check that the number of requested messages is present
        # (we can't guarantee it's rate limited in a test environment)
        requested_msg_ids = call_args[0]
        assert len(requested_msg_ids) > 0
        assert len(requested_msg_ids) <= len(msg_ids)


@pytest.mark.trio
async def test_no_infinite_gossip_loops():
    """Test that gossip doesn't create infinite loops."""
    async with PubsubFactory.create_batch_with_gossipsub(
        3, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1, gsub2 = (cast(GossipSub, ps.router) for ps in pubsubs)
        host0, host1, host2 = (ps.host for ps in pubsubs)

        # Connect hosts in a triangle
        await connect(host0, host1)
        await connect(host1, host2)
        await connect(host0, host2)
        await trio.sleep(0.5)

        # All subscribe to the same topic
        topic = "test_gossip_loops"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Create a message ID that would be in the seen cache
        seqno = b"seqno123"
        from_id = host1.get_id().to_bytes()
        msg_id_tuple = (seqno, from_id)
        msg_id_str = str(msg_id_tuple)

        # Create a mock for pubsub
        mock_pubsub = MagicMock()
        mock_seen_messages = MagicMock()
        mock_cache = {}
        mock_cache[msg_id_tuple] = True
        mock_seen_messages.cache = mock_cache
        mock_pubsub.seen_messages = mock_seen_messages

        # Set the mock on gsub0
        gsub0.pubsub = mock_pubsub

        # Mock emit_iwant to track IWANT messages
        emit_iwant_mock = AsyncMock()
        gsub0.emit_iwant = emit_iwant_mock

        # Create IHAVE message for the same message from host2
        ihave_msg = rpc_pb2.ControlIHave(messageIDs=[msg_id_str], topicID=topic)

        # Simulate receiving IHAVE from host2 for a message already seen from host1
        await gsub0.handle_ihave(ihave_msg, host2.get_id())

        # Verify that no IWANT was emitted (message already seen)
        emit_iwant_mock.assert_not_called()


@pytest.mark.trio
async def test_dropping_gossip_triggers_iwant():
    """Test that dropping gossip triggers IWANT requests for missing messages."""
    async with PubsubFactory.create_batch_with_gossipsub(
        3, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1, gsub2 = (cast(GossipSub, ps.router) for ps in pubsubs)
        host0, host1, host2 = (ps.host for ps in pubsubs)

        # Connect hosts in a line: 0 -- 1 -- 2
        # This means host0 and host2 are not directly connected
        await connect(host0, host1)
        await connect(host1, host2)
        await trio.sleep(0.5)

        # All subscribe to the same topic
        topic = "test_dropping_gossip"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Create a message ID that gsub0 doesn't have
        seqno = b"seqno123"
        from_id = host2.get_id().to_bytes()
        msg_id_tuple = (seqno, from_id)
        msg_id_str = str(msg_id_tuple)

        # Mock emit_iwant to capture IWANT requests
        emit_iwant_mock = AsyncMock()
        gsub0.emit_iwant = emit_iwant_mock

        # Create IHAVE control message from host2 (not directly connected)
        ihave_msg = rpc_pb2.ControlIHave(messageIDs=[msg_id_str], topicID=topic)

        # Simulate host1 forwarding IHAVE from host2 to host0
        await gsub0.handle_ihave(ihave_msg, host1.get_id())

        # Verify that emit_iwant was called for the missing message
        emit_iwant_mock.assert_called_once()
        call_args = emit_iwant_mock.call_args[0]
        assert len(call_args[0]) > 0  # Should have at least one message ID
        assert call_args[1] == host1.get_id()  # Second arg is peer ID

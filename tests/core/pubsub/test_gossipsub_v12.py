import pytest
import trio

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V12,
    GossipSub,
)
from libp2p.pubsub.pb import rpc_pb2
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    IDFactory,
    PubsubFactory,
)
from tests.utils.pubsub.utils import (
    one_to_all_connect,
)


@pytest.mark.trio
async def test_gossipsub_v12_protocol_support():
    """Test that GossipSub supports protocol v1.2."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V12], max_idontwant_messages=5
    ) as pubsubs_gsub:
        # Verify the protocol is registered correctly
        for pubsub in pubsubs_gsub:
            if isinstance(pubsub.router, GossipSub):
                assert PROTOCOL_ID_V12 in pubsub.router.protocols
                assert pubsub.router.max_idontwant_messages == 5


@pytest.mark.trio
async def test_idontwant_data_structures():
    """Test IDONTWANT data structure initialization and cleanup."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V12]
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Initially empty
        assert len(router.dont_send_message_ids) == 0

        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.1)

        # Verify peer tracking is initialized
        peer_id = pubsubs_gsub[1].host.get_id()
        assert peer_id in router.dont_send_message_ids
        assert isinstance(router.dont_send_message_ids[peer_id], set)
        assert len(router.dont_send_message_ids[peer_id]) == 0


@pytest.mark.trio
async def test_handle_idontwant_message():
    """Test handling of incoming IDONTWANT control messages."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V12]
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.1)

        sender_peer_id = pubsubs_gsub[1].host.get_id()

        # Create IDONTWANT message
        msg_ids = [b"msg1", b"msg2", b"msg3"]
        idontwant_msg = rpc_pb2.ControlIDontWant()
        idontwant_msg.messageIDs.extend(msg_ids)

        # Handle the IDONTWANT message
        await router.handle_idontwant(idontwant_msg, sender_peer_id)

        # Verify message IDs are stored
        assert sender_peer_id in router.dont_send_message_ids
        stored_ids = router.dont_send_message_ids[sender_peer_id]
        for msg_id in msg_ids:
            assert msg_id in stored_ids


@pytest.mark.trio
async def test_message_filtering_with_idontwant():
    """Test that messages are filtered based on IDONTWANT."""
    async with PubsubFactory.create_batch_with_gossipsub(
        3,
        protocols=[PROTOCOL_ID_V12],
        heartbeat_interval=100,  # Disable heartbeat
    ) as pubsubs_gsub:
        topic = "test_topic"

        # Connect all peers
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        await one_to_all_connect(hosts, 0)
        await trio.sleep(0.1)

        # Subscribe all to the topic
        for pubsub in pubsubs_gsub:
            await pubsub.subscribe(topic)
        await trio.sleep(0.5)  # Allow mesh to form

        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Create a fake message
        msg_id = b"test_msg_id"
        msg_forwarder = pubsubs_gsub[1].host.get_id()
        origin = pubsubs_gsub[2].host.get_id()

        # Add IDONTWANT for peer 1
        peer1_id = pubsubs_gsub[1].host.get_id()
        router.dont_send_message_ids[peer1_id].add(msg_id)

        # Get peers to send to
        peers_to_send = list(
            router._get_peers_to_send([topic], msg_forwarder, origin, msg_id)
        )

        # Peer 1 should be filtered out due to IDONTWANT
        assert peer1_id not in peers_to_send

        # But peer 2 should still be included
        peer2_id = pubsubs_gsub[2].host.get_id()
        # Note: peer2 is origin, so won't be in the list
        # Let's test with peer 2 as forwarder instead
        peers_to_send_alt = list(
            router._get_peers_to_send([topic], peer2_id, origin, msg_id)
        )

        # Peer 1 should still be filtered out
        assert peer1_id not in peers_to_send_alt


@pytest.mark.trio
async def test_idontwant_pruning():
    """Test that IDONTWANT entries are pruned during heartbeat."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2,
        protocols=[PROTOCOL_ID_V12],
        heartbeat_interval=100,  # Disable auto heartbeat
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.1)

        peer_id = pubsubs_gsub[1].host.get_id()

        # Add some IDONTWANT entries
        router.dont_send_message_ids[peer_id].add(b"msg1")
        router.dont_send_message_ids[peer_id].add(b"msg2")
        assert len(router.dont_send_message_ids[peer_id]) == 2

        # Run pruning
        router._prune_idontwant_entries()

        # Verify entries are cleared
        assert len(router.dont_send_message_ids[peer_id]) == 0


@pytest.mark.trio
async def test_emit_idontwant():
    """Test emitting IDONTWANT control messages."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V12]
    ) as pubsubs_gsub:
        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.1)

        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        peer_id = pubsubs_gsub[1].host.get_id()
        msg_ids = [b"msg1", b"msg2"]

        # This should not raise an exception
        await router.emit_idontwant(msg_ids, peer_id)

        # Note: Testing actual message delivery would require more complex
        # test setup to capture the sent messages


@pytest.mark.trio
async def test_mixed_protocol_versions():
    """Test that IDONTWANT is only sent to v1.2 peers."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V12]
    ) as v12_pubsubs:
        router = v12_pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Mock different protocol versions for testing
        from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11

        peer_id_v11 = IDFactory()
        peer_id_v12 = IDFactory()

        # Add peers with different protocol versions
        router.add_peer(peer_id_v11, PROTOCOL_ID_V11)
        router.add_peer(peer_id_v12, PROTOCOL_ID_V12)

        # Create mock mesh
        topic = "test_topic"
        router.mesh[topic] = {peer_id_v11, peer_id_v12}

        # Mock message ID
        msg_id = b"test_message"

        # The emit function should handle protocol filtering internally
        # This should not raise an exception - it should only attempt to
        # send IDONTWANT to v1.2 peers
        await router._emit_idontwant_for_message(msg_id, [topic])

        # Verify that the method completed without error
        # (In a real implementation, we'd verify the actual message sending,
        # but that would require more complex mocking)


@pytest.mark.trio
async def test_max_idontwant_messages_limit():
    """Test that max_idontwant_messages limit is enforced."""
    max_limit = 5  # Small limit for testing

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V12], max_idontwant_messages=max_limit
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.1)

        sender_peer_id = pubsubs_gsub[1].host.get_id()

        # First batch - should be accepted completely
        first_batch = [f"msg{i}".encode() for i in range(max_limit)]
        first_idontwant = rpc_pb2.ControlIDontWant()
        first_idontwant.messageIDs.extend(first_batch)

        await router.handle_idontwant(first_idontwant, sender_peer_id)

        # Verify all messages were stored
        assert len(router.dont_send_message_ids[sender_peer_id]) == max_limit
        for msg_id in first_batch:
            assert msg_id in router.dont_send_message_ids[sender_peer_id]

        # Second batch - should cause older entries to be dropped
        second_batch = [f"new_msg{i}".encode() for i in range(3)]
        second_idontwant = rpc_pb2.ControlIDontWant()
        second_idontwant.messageIDs.extend(second_batch)

        await router.handle_idontwant(second_idontwant, sender_peer_id)

        # Verify total count stays at or below the limit
        assert len(router.dont_send_message_ids[sender_peer_id]) <= max_limit

        # Verify some of the new messages are present
        found_new = False
        for msg_id in second_batch:
            if msg_id in router.dont_send_message_ids[sender_peer_id]:
                found_new = True
                break

        assert found_new, "None of the new messages were stored"

        # Verify some of the old messages were dropped
        found_old = 0
        for msg_id in first_batch:
            if msg_id in router.dont_send_message_ids[sender_peer_id]:
                found_old += 1

        assert found_old < len(first_batch), "None of the old messages were dropped"

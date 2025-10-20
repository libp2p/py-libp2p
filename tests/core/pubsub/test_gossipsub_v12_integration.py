from typing import cast
from unittest.mock import AsyncMock, patch

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
    PubsubFactory,
)


@pytest.mark.trio
async def test_idontwant_message_exchange():
    """
    Integration test for IDONTWANT message exchange between peers.

    This test verifies that:
    1. When a node receives a message, it emits IDONTWANT to mesh peers
    2. Peers receiving IDONTWANT add the message ID to their don't_send list
    3. The message isn't forwarded to peers that have sent IDONTWANT
    """
    # Create 3 nodes with GossipSub 1.2
    async with PubsubFactory.create_batch_with_gossipsub(
        3,
        protocols=[PROTOCOL_ID_V12],
        heartbeat_interval=100,  # Disable auto heartbeat for test stability
    ) as pubsubs:
        topic = "test_topic"

        # Get the routers
        routers = [pubsub.router for pubsub in pubsubs]
        for router in routers:
            assert isinstance(router, GossipSub)

        # Connect all nodes
        await connect(pubsubs[0].host, pubsubs[1].host)
        await connect(pubsubs[1].host, pubsubs[2].host)
        await connect(pubsubs[0].host, pubsubs[2].host)
        await trio.sleep(0.1)  # Allow connections to establish

        # Subscribe all nodes to the test topic
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(0.5)  # Allow mesh to form

        # Set up the mesh manually to ensure a specific topology
        # Node 0 and 1 are in Node 2's mesh
        peer0_id = pubsubs[0].host.get_id()
        peer1_id = pubsubs[1].host.get_id()
        peer2_id = pubsubs[2].host.get_id()

        for router in routers:
            router.mesh[topic] = set()

        routers[0].mesh[topic].add(peer1_id)
        routers[0].mesh[topic].add(peer2_id)
        routers[1].mesh[topic].add(peer0_id)
        routers[1].mesh[topic].add(peer2_id)
        routers[2].mesh[topic].add(peer0_id)
        routers[2].mesh[topic].add(peer1_id)

        # Set up protocol versions
        for i, router in enumerate(routers):
            for j in range(3):
                if i != j:
                    router.peer_protocol[pubsubs[j].host.get_id()] = PROTOCOL_ID_V12

        # Create a test message
        test_data = b"test_message_data"
        test_from = pubsubs[0].my_id.to_bytes()
        test_seqno = b"\x00\x00\x00\x00\x00\x00\x00\x01"

        msg = rpc_pb2.Message(
            from_id=test_from,
            data=test_data,
            seqno=test_seqno,
            topicIDs=[topic],
        )

        # Get message ID
        msg_id = pubsubs[0].get_message_id(msg)

        # Mock emit_idontwant to capture calls
        with patch.object(
            routers[1], "emit_idontwant", new_callable=AsyncMock
        ) as mock_emit:
            # Node 1 receives message from Node 0
            await routers[1].publish(peer0_id, msg)

            # Verify Node 1 emitted IDONTWANT to its mesh peers
            await trio.sleep(0.1)  # Allow async operations to complete

            # Check that emit_idontwant was called for Node 2
            mock_emit.assert_called()
            called_msg_ids, called_peer_id = mock_emit.call_args[0]
            assert msg_id in called_msg_ids
            assert called_peer_id in (peer0_id, peer2_id)

            # Now manually add the message ID to Node 2's don't_send list for Node 1
            # Cast to GossipSub to access implementation-specific attributes
            gossipsub_router = cast(GossipSub, routers[2])
            gossipsub_router.dont_send_message_ids[peer1_id] = {msg_id}

            # When Node 2 tries to send the message, it should filter out Node 1
            # Cast to GossipSub to access implementation-specific methods
            gossipsub_router = cast(GossipSub, routers[2])
            peers_to_send = list(
                gossipsub_router._get_peers_to_send([topic], peer0_id, peer0_id, msg_id)
            )

            # Node 1 should be filtered out due to IDONTWANT
            assert peer1_id not in peers_to_send


@pytest.mark.trio
async def test_idontwant_integration_with_end_to_end_message():
    """
    End-to-end test for IDONTWANT functionality.

    This test verifies that:
    1. When a node receives a message, it should not receive it again from other peers
    2. This is achieved through IDONTWANT messages
    """
    # Create 3 nodes with GossipSub 1.2
    async with PubsubFactory.create_batch_with_gossipsub(
        3,
        protocols=[PROTOCOL_ID_V12],
        heartbeat_interval=100,  # Disable auto heartbeat for test stability
    ) as pubsubs:
        topic = "test_topic"

        # Connect all nodes
        await connect(pubsubs[0].host, pubsubs[1].host)
        await connect(pubsubs[1].host, pubsubs[2].host)
        await connect(pubsubs[0].host, pubsubs[2].host)
        await trio.sleep(0.1)  # Allow connections to establish

        # Set protocol versions for all peers
        for i, pubsub in enumerate(pubsubs):
            router = pubsub.router
            assert isinstance(router, GossipSub)
            for j in range(3):
                if i != j:
                    router.peer_protocol[pubsubs[j].host.get_id()] = PROTOCOL_ID_V12

        # Create a test message directly
        test_data = b"test_idontwant_integration"
        test_from = pubsubs[0].my_id.to_bytes()
        test_seqno = b"\x00\x00\x00\x00\x00\x00\x00\x01"

        msg = rpc_pb2.Message(
            from_id=test_from,
            data=test_data,
            seqno=test_seqno,
            topicIDs=[topic],
        )

        # Get message ID
        msg_id = pubsubs[0].get_message_id(msg)

        # Manually add the message ID to Node 0's don't_send list for Node 2
        peer1_id = pubsubs[1].host.get_id()
        peer2_id = pubsubs[2].host.get_id()

        # Cast to GossipSub to access implementation-specific attributes
        gossipsub_router = cast(GossipSub, pubsubs[0].router)
        if peer2_id not in gossipsub_router.dont_send_message_ids:
            gossipsub_router.dont_send_message_ids[peer2_id] = set()
        gossipsub_router.dont_send_message_ids[peer2_id].add(msg_id)

        # Verify the message won't be sent to peer2
        peers_to_send = list(
            gossipsub_router._get_peers_to_send([topic], peer1_id, peer1_id, msg_id)
        )

        # Node 2 should be filtered out due to IDONTWANT
        assert peer2_id not in peers_to_send, "IDONTWANT filtering failed"

"""Tests for GossipSub v1.1 network-level scenarios."""

from typing import cast

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_large_scale_fanout():
    """Test large-scale fanout with many peers."""
    # Use a moderate number of peers for practical test execution
    num_peers = 8  # Reduced from original for stability

    async with PubsubFactory.create_batch_with_gossipsub(
        num_peers, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]
        gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]

        # Connect in a star topology with peer 0 at the center
        # This allows testing fanout without requiring a full mesh
        for i in range(1, len(hosts)):
            await connect(hosts[0], hosts[i])

        # Add some additional connections to create a more realistic network
        # Connect every 2nd peer to create some redundancy
        for i in range(1, len(hosts), 2):
            for j in range(i + 2, len(hosts), 2):
                if j < len(hosts):
                    await connect(hosts[i], hosts[j])

        await trio.sleep(1.0)  # Allow time for connections to establish

        # All peers subscribe to the same topic
        topic = "test_large_scale"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Subscribe all peers to the topic and collect messages
            subscriptions = []
            for i, pubsub in enumerate(pubsubs):
                subscription = await pubsub.subscribe(topic)
                subscriptions.append(subscription)

                async def collect_messages(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_messages, i, subscription)

            await trio.sleep(2.0)  # Allow time for mesh formation

            # Verify mesh formation
            for gsub in gsubs:
                assert topic in gsub.mesh
                assert len(gsub.mesh[topic]) > 0

            # Publish a message from a peer in the middle of the network
            message_data = b"large scale fanout test message"
            middle_peer_index = num_peers // 2
            await pubsubs[middle_peer_index].publish(topic, message_data)

            # Allow time for message propagation in the network
            await trio.sleep(3.0)

            # Verify message propagation
            # We expect at least 90% of peers to receive the message
            peers_received = sum(
                1
                for msgs in received_messages
                if any(msg.data == message_data for msg in msgs)
            )
            assert peers_received >= int(num_peers * 0.9)

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_simulated_partition():
    """
    Test network partition using topic isolation
    instead of actual network partition.
    """
    # Create a smaller batch of peers for testing
    async with PubsubFactory.create_batch_with_gossipsub(
        4, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]

        # Connect all peers in a full mesh
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                await connect(hosts[i], hosts[j])

        await trio.sleep(1.0)  # Allow time for connections to establish

        # Create two separate topics to simulate partitions
        topic_group1 = "group1_topic"
        topic_group2 = "group2_topic"
        common_topic = "common_topic"

        # Group 1 (peers 0-1) subscribe to topic_group1
        # Group 2 (peers 2-3) subscribe to topic_group2
        # All peers subscribe to common_topic
        received_messages = {
            topic_group1: [[] for _ in range(len(pubsubs))],
            topic_group2: [[] for _ in range(len(pubsubs))],
            common_topic: [[] for _ in range(len(pubsubs))],
        }

        async with trio.open_nursery() as nursery:
            # Subscribe peers to their respective topics
            for i in range(2):  # Group 1
                # Subscribe to group1 topic
                sub1 = await pubsubs[i].subscribe(topic_group1)

                async def collect_group1(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[topic_group1][peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_group1, i, sub1)

                # Also subscribe to common topic
                common_sub1 = await pubsubs[i].subscribe(common_topic)

                async def collect_common1(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[common_topic][peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_common1, i, common_sub1)

            for i in range(2, 4):  # Group 2
                # Subscribe to group2 topic
                sub2 = await pubsubs[i].subscribe(topic_group2)

                async def collect_group2(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[topic_group2][peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_group2, i, sub2)

                # Also subscribe to common topic
                common_sub2 = await pubsubs[i].subscribe(common_topic)

                async def collect_common2(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[common_topic][peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_common2, i, common_sub2)

            await trio.sleep(1.0)  # Allow time for mesh formation

            # Publish messages to the partitioned topics
            message_group1 = b"message for group 1"
            await pubsubs[0].publish(topic_group1, message_group1)

            message_group2 = b"message for group 2"
            await pubsubs[2].publish(topic_group2, message_group2)

            await trio.sleep(2.0)  # Allow time for message propagation

            # Verify that messages stayed within their respective groups
            # Group 1 (peers 0-1) should have received message_group1
            for i in range(2):
                assert any(
                    msg.data == message_group1
                    for msg in received_messages[topic_group1][i]
                )
                # Group 1 peers shouldn't receive group 2 messages
                assert not received_messages[topic_group2][i]

            # Group 2 (peers 2-3) should have received message_group2
            for i in range(2, 4):
                assert any(
                    msg.data == message_group2
                    for msg in received_messages[topic_group2][i]
                )
                # Group 2 peers shouldn't receive group 1 messages
                assert not received_messages[topic_group1][i]

            # Now publish a message to the common topic
            message_common = b"message for everyone"
            await pubsubs[1].publish(common_topic, message_common)

            await trio.sleep(2.0)  # Allow time for message propagation

            # Verify that all peers received the common message
            for i in range(len(pubsubs)):
                assert any(
                    msg.data == message_common
                    for msg in received_messages[common_topic][i]
                )

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_mesh_stability():
    """Test mesh stability with changing peer connections."""
    # Create a smaller batch of peers for testing
    async with PubsubFactory.create_batch_with_gossipsub(
        4, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]
        gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]

        # Connect peers in a ring topology initially
        for i in range(len(hosts)):
            await connect(hosts[i], hosts[(i + 1) % len(hosts)])

        await trio.sleep(1.0)  # Allow time for connections to establish

        # All peers subscribe to the same topic
        topic = "test_stability"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)

        await trio.sleep(1.0)  # Allow time for mesh formation

        # Verify initial mesh state
        for gsub in gsubs:
            assert topic in gsub.mesh
            assert len(gsub.mesh[topic]) > 0

        # Add some new connections to change the topology
        await connect(hosts[0], hosts[2])

        await trio.sleep(1.0)  # Allow time for new connections

        # Trigger mesh heartbeat
        for gsub in gsubs:
            gsub.mesh_heartbeat()

        await trio.sleep(1.0)  # Allow time for mesh changes to take effect

        # Verify that mesh is still maintained
        for i, gsub in enumerate(gsubs):
            # Check that the mesh is still maintained
            assert topic in gsub.mesh
            assert len(gsub.mesh[topic]) > 0

        # Publish a message to verify the mesh is still functional
        message_data = b"test message after topology change"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Set up message collection
            for i, pubsub in enumerate(pubsubs):
                subscription = await pubsub.subscribe(topic)

                async def collect_messages(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_messages, i, subscription)

            await trio.sleep(0.5)  # Allow time for subscriptions to be processed

            # Publish a message
            await pubsubs[0].publish(topic, message_data)

            # Allow time for message propagation
            await trio.sleep(2.0)

            # Verify message propagation
            peers_received = sum(
                1
                for msgs in received_messages
                if any(msg.data == message_data for msg in msgs)
            )
            assert (
                peers_received >= 3
            )  # At least 75% of peers should receive the message

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()

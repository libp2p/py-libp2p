"""Tests for GossipSub v1.1 network-level scenarios."""

from typing import cast

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory
from tests.utils.pubsub.wait import wait_for


async def _wait_connected_pair(pubsubs, i: int, j: int) -> None:
    await pubsubs[i].wait_for_peer(pubsubs[j].my_id)
    await pubsubs[j].wait_for_peer(pubsubs[i].my_id)


async def _wait_subscription_pair(pubsubs, i: int, j: int, topic: str) -> None:
    await pubsubs[i].wait_for_subscription(pubsubs[j].my_id, topic)
    await pubsubs[j].wait_for_subscription(pubsubs[i].my_id, topic)


async def _wait_mesh_pair(pubsubs, i: int, j: int, topic: str) -> None:
    await pubsubs[i].wait_for_mesh(pubsubs[j].my_id, topic)
    await pubsubs[j].wait_for_mesh(pubsubs[i].my_id, topic)


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
        edges: list[tuple[int, int]] = []
        for i in range(1, len(hosts)):
            await connect(hosts[0], hosts[i])
            edges.append((0, i))

        # Add some additional connections to create a more realistic network
        # Connect every 2nd peer to create some redundancy
        for i in range(1, len(hosts), 2):
            for j in range(i + 2, len(hosts), 2):
                if j < len(hosts):
                    await connect(hosts[i], hosts[j])
                    edges.append((i, j))

        for i, j in edges:
            await _wait_connected_pair(pubsubs, i, j)

        # All peers subscribe to the same topic
        topic = "test_large_scale"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Subscribe all peers to the topic and collect messages
            for i, pubsub in enumerate(pubsubs):
                subscription = await pubsub.subscribe(topic)

                async def collect_messages(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_messages, i, subscription)

            for i, j in edges:
                await _wait_subscription_pair(pubsubs, i, j, topic)

            await wait_for(
                lambda: all(
                    topic in gsub.mesh and len(gsub.mesh[topic]) > 0 for gsub in gsubs
                ),
                timeout=10.0,
                fail_msg="Large-scale mesh did not form",
            )

            # Verify mesh formation
            for gsub in gsubs:
                assert topic in gsub.mesh
                assert len(gsub.mesh[topic]) > 0

            # Publish a message from a peer in the middle of the network
            message_data = b"large scale fanout test message"
            middle_peer_index = num_peers // 2
            await pubsubs[middle_peer_index].publish(topic, message_data)

            # Wait until at least 90% of peers receive the message
            min_received = int(num_peers * 0.9)
            await wait_for(
                lambda: sum(
                    1
                    for msgs in received_messages
                    if any(msg.data == message_data for msg in msgs)
                )
                >= min_received,
                timeout=10.0,
                fail_msg=(
                    f"Fewer than {min_received}/{num_peers} peers received "
                    "large-scale fanout message"
                ),
            )

            peers_received = sum(
                1
                for msgs in received_messages
                if any(msg.data == message_data for msg in msgs)
            )
            assert peers_received >= min_received

            # Unsubscribe before cancel so late deliveries cannot schedule
            # push_msg on a closing Swarm nursery under CI load.
            for ps in pubsubs:
                await ps.unsubscribe(topic)
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
        edges = []
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                await connect(hosts[i], hosts[j])
                edges.append((i, j))

        for i, j in edges:
            await _wait_connected_pair(pubsubs, i, j)

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

            # Group-topic mesh between peers that share the topic
            await _wait_subscription_pair(pubsubs, 0, 1, topic_group1)
            await _wait_mesh_pair(pubsubs, 0, 1, topic_group1)
            await _wait_subscription_pair(pubsubs, 2, 3, topic_group2)
            await _wait_mesh_pair(pubsubs, 2, 3, topic_group2)
            for i, j in edges:
                await _wait_subscription_pair(pubsubs, i, j, common_topic)
                await _wait_mesh_pair(pubsubs, i, j, common_topic)

            # Publish messages to the partitioned topics
            message_group1 = b"message for group 1"
            await pubsubs[0].publish(topic_group1, message_group1)

            message_group2 = b"message for group 2"
            await pubsubs[2].publish(topic_group2, message_group2)

            await wait_for(
                lambda: all(
                    any(
                        msg.data == message_group1
                        for msg in received_messages[topic_group1][i]
                    )
                    for i in range(2)
                )
                and all(
                    any(
                        msg.data == message_group2
                        for msg in received_messages[topic_group2][i]
                    )
                    for i in range(2, 4)
                ),
                timeout=10.0,
                fail_msg="Partitioned group messages did not arrive",
            )

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

            await wait_for(
                lambda: all(
                    any(
                        msg.data == message_common
                        for msg in received_messages[common_topic][i]
                    )
                    for i in range(len(pubsubs))
                ),
                timeout=10.0,
                fail_msg="Common-topic message did not reach all peers",
            )

            # Verify that all peers received the common message
            for i in range(len(pubsubs)):
                assert any(
                    msg.data == message_common
                    for msg in received_messages[common_topic][i]
                )

            for ps in pubsubs:
                await ps.unsubscribe(topic_group1)
                await ps.unsubscribe(topic_group2)
                await ps.unsubscribe(common_topic)
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
        ring_edges = [(i, (i + 1) % len(hosts)) for i in range(len(hosts))]
        for i, j in ring_edges:
            await connect(hosts[i], hosts[j])
        for i, j in ring_edges:
            await _wait_connected_pair(pubsubs, i, j)

        # All peers subscribe to the same topic
        topic = "test_stability"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)

        for i, j in ring_edges:
            await _wait_subscription_pair(pubsubs, i, j, topic)
            await _wait_mesh_pair(pubsubs, i, j, topic)

        # Verify initial mesh state
        for gsub in gsubs:
            assert topic in gsub.mesh
            assert len(gsub.mesh[topic]) > 0

        # Add some new connections to change the topology
        await connect(hosts[0], hosts[2])
        await _wait_connected_pair(pubsubs, 0, 2)
        await _wait_subscription_pair(pubsubs, 0, 2, topic)

        # Trigger mesh heartbeat
        for gsub in gsubs:
            gsub.mesh_heartbeat()

        # Wait until mesh remains non-empty after topology change
        await wait_for(
            lambda: all(
                topic in gsub.mesh and len(gsub.mesh[topic]) > 0 for gsub in gsubs
            ),
            timeout=10.0,
            fail_msg="Mesh not maintained after topology change",
        )

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

            # Already subscribed; ensure collectors are attached and mesh ready
            await wait_for(
                lambda: all(
                    topic in gsub.mesh and len(gsub.mesh[topic]) > 0 for gsub in gsubs
                ),
                timeout=10.0,
                fail_msg="Mesh not ready before stability publish",
            )

            # Publish a message
            await pubsubs[0].publish(topic, message_data)

            # Wait until at least 75% of peers receive the message
            await wait_for(
                lambda: sum(
                    1
                    for msgs in received_messages
                    if any(msg.data == message_data for msg in msgs)
                )
                >= 3,
                timeout=10.0,
                fail_msg="Fewer than 3 peers received message after topology change",
            )

            # Verify message propagation
            peers_received = sum(
                1
                for msgs in received_messages
                if any(msg.data == message_data for msg in msgs)
            )
            assert (
                peers_received >= 3
            )  # At least 75% of peers should receive the message

            for ps in pubsubs:
                await ps.unsubscribe(topic)
            nursery.cancel_scope.cancel()

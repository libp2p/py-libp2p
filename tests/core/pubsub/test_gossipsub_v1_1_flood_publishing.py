"""
Tests for Gossipsub v1.1 Flood Publishing functionality.

This module tests the flood publishing mechanism in GossipSub v1.1, which
ensures messages are delivered reliably even when published from non-mesh peers.
"""

import pytest
import trio

from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory
from tests.utils.pubsub.wait import (
    wait_for,
    wait_for_pubsub_payload,
    wait_for_pubsub_payloads,
)


async def _wait_star_peers(pubsubs) -> None:
    """Wait until hub peer 0 has pubsub streams with every spoke."""
    for i in range(1, len(pubsubs)):
        await pubsubs[0].wait_for_peer(pubsubs[i].my_id)
        await pubsubs[i].wait_for_peer(pubsubs[0].my_id)


async def _wait_line_peers(pubsubs) -> None:
    """Wait until each adjacent pair in a line topology is connected."""
    for i in range(len(pubsubs) - 1):
        await pubsubs[i].wait_for_peer(pubsubs[i + 1].my_id)
        await pubsubs[i + 1].wait_for_peer(pubsubs[i].my_id)


async def _wait_full_mesh_peers(pubsubs) -> None:
    """Wait until every pair has a pubsub stream."""
    for i in range(len(pubsubs)):
        for j in range(i + 1, len(pubsubs)):
            await pubsubs[i].wait_for_peer(pubsubs[j].my_id)
            await pubsubs[j].wait_for_peer(pubsubs[i].my_id)


async def _wait_topic_ready(pubsubs, topic: str, edges: list[tuple[int, int]]) -> None:
    """Wait for peer subscriptions on each edge, then non-empty local meshes."""
    for i, j in edges:
        await pubsubs[i].wait_for_subscription(pubsubs[j].my_id, topic)
        await pubsubs[j].wait_for_subscription(pubsubs[i].my_id, topic)

    subscribed = [ps for ps in pubsubs if topic in ps.topic_ids]
    if not subscribed:
        return

    await wait_for(
        lambda: all(
            topic in cast_mesh(ps) and len(cast_mesh(ps)[topic]) > 0
            for ps in subscribed
        ),
        timeout=10.0,
        fail_msg=f"Mesh for {topic!r} did not form on subscribed peers",
    )


def cast_mesh(pubsub):
    """Return router.mesh for mesh-readiness predicates."""
    return pubsub.router.mesh


@pytest.mark.trio
async def test_publish_from_non_mesh_peer():
    """Test that publishing from a non-mesh peer delivers messages reliably."""
    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        5, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]

        # Connect in a specific topology: 0 connects to all others
        # but others don't connect to each other directly
        for i in range(1, len(hosts)):
            await connect(hosts[0], hosts[i])
        await _wait_star_peers(pubsubs)

        # Only peers 1-4 subscribe to the topic
        topic = "test_flood_publish"
        subs = []
        for i in range(1, len(pubsubs)):
            subs.append(await pubsubs[i].subscribe(topic))

        # Publisher is not subscribed; wait until it sees spoke subscriptions.
        for i in range(1, len(pubsubs)):
            await pubsubs[0].wait_for_subscription(pubsubs[i].my_id, topic)

        # Peer 0 is not subscribed but will publish to the topic
        message_data = b"flood published message"
        await pubsubs[0].publish(topic, message_data)

        for i, sub in enumerate(subs, start=1):
            await wait_for_pubsub_payload(
                sub,
                message_data,
                fail_msg=f"Peer {i} did not receive flood-published message",
            )


@pytest.mark.trio
async def test_flood_publish_with_mesh_formation():
    """Test that flood publishing works even before mesh formation."""
    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        4, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]

        # Connect in a line topology: 0 - 1 - 2 - 3
        for i in range(len(hosts) - 1):
            await connect(hosts[i], hosts[i + 1])
        await _wait_line_peers(pubsubs)

        # All peers subscribe to the topic
        topic = "test_flood_publish_mesh_formation"
        subs = []
        for pubsub in pubsubs:
            subs.append(await pubsub.subscribe(topic))

        edges = [(i, i + 1) for i in range(len(pubsubs) - 1)]
        await _wait_topic_ready(pubsubs, topic, edges)

        # Publish after mesh readiness on the line
        message_data = b"early message"
        await pubsubs[0].publish(topic, message_data)

        # In a line topology, at least the publisher should receive the message
        await wait_for_pubsub_payload(
            subs[0],
            message_data,
            fail_msg="Publisher did not receive its own early message",
        )


@pytest.mark.trio
async def test_flood_publish_reliability():
    """Test that flood publishing is reliable under various network conditions."""
    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        6, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]

        # Connect in a star topology with peer 0 at the center
        for i in range(1, len(hosts)):
            await connect(hosts[0], hosts[i])
        # Add some additional connections for redundancy
        await connect(hosts[1], hosts[2])
        await connect(hosts[3], hosts[4])
        await connect(hosts[4], hosts[5])
        await _wait_star_peers(pubsubs)
        await pubsubs[1].wait_for_peer(pubsubs[2].my_id)
        await pubsubs[2].wait_for_peer(pubsubs[1].my_id)
        await pubsubs[3].wait_for_peer(pubsubs[4].my_id)
        await pubsubs[4].wait_for_peer(pubsubs[3].my_id)
        await pubsubs[4].wait_for_peer(pubsubs[5].my_id)
        await pubsubs[5].wait_for_peer(pubsubs[4].my_id)

        # All peers subscribe to the topic
        topic = "test_flood_publish_reliability"
        subs = []
        for pubsub in pubsubs:
            subs.append(await pubsub.subscribe(topic))

        edges = [(0, i) for i in range(1, len(pubsubs))] + [(1, 2), (3, 4), (4, 5)]
        await _wait_topic_ready(pubsubs, topic, edges)

        # Publish multiple messages from different peers
        messages = []
        for i in range(3):
            message_data = f"message_{i}".encode()
            messages.append(message_data)
            await pubsubs[i].publish(topic, message_data)

        # Verify that all peers received all messages
        for i, sub in enumerate(subs):
            await wait_for_pubsub_payloads(
                sub,
                messages,
                fail_msg=f"Peer {i} missing one or more reliability messages",
            )


@pytest.mark.trio
async def test_flood_publish_with_disconnected_peers():
    """Test that flood publishing works even with some disconnected peers."""
    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        5, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]

        # Connect in a specific topology: 0 connects to 1, 2
        # and 3 connects to 2, 4
        await connect(hosts[0], hosts[1])
        await connect(hosts[0], hosts[2])
        await connect(hosts[3], hosts[2])
        await connect(hosts[3], hosts[4])
        for i, j in [(0, 1), (0, 2), (3, 2), (3, 4)]:
            await pubsubs[i].wait_for_peer(pubsubs[j].my_id)
            await pubsubs[j].wait_for_peer(pubsubs[i].my_id)

        # All peers subscribe to the topic
        topic = "test_flood_publish_disconnected"
        subs = []
        for pubsub in pubsubs:
            subs.append(await pubsub.subscribe(topic))

        edges = [(0, 1), (0, 2), (3, 2), (3, 4)]
        await _wait_topic_ready(pubsubs, topic, edges)

        # Publish from peer 0
        message_data = b"message from peer 0"
        await pubsubs[0].publish(topic, message_data)

        # Verify that peers 0, 1, 2 received the message
        # (peers 3, 4 might not receive it due to network topology)
        for i in range(3):
            await wait_for_pubsub_payload(
                subs[i],
                message_data,
                fail_msg=f"Peer {i} did not receive the message",
            )

        # Publish from peer 4
        message_data = b"message from peer 4"
        await pubsubs[4].publish(topic, message_data)

        # Verify that peers 2, 3, 4 received the message
        # (peers 0, 1 might not receive it due to network topology)
        for i in [2, 3, 4]:
            await wait_for_pubsub_payload(
                subs[i],
                message_data,
                fail_msg=f"Peer {i} did not receive the message",
            )


@pytest.mark.trio
async def test_flood_publish_with_high_frequency():
    """Test that flood publishing works with high frequency messages."""
    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        4, heartbeat_interval=0.5
    ) as pubsubs:
        hosts = [ps.host for ps in pubsubs]

        # Connect in a mesh topology
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                await connect(hosts[i], hosts[j])
        await _wait_full_mesh_peers(pubsubs)

        topic = "test_flood_publish_high_frequency"
        # Publisher also subscribes so mesh forms symmetrically; receivers keep
        # subscription handles for delivery waits (avoid background nursery cancel
        # races that close the Swarm service nursery under CI load).
        await pubsubs[0].subscribe(topic)
        subs = []
        for i in range(1, len(pubsubs)):
            subs.append(await pubsubs[i].subscribe(topic))

        edges = [
            (i, j) for i in range(len(pubsubs)) for j in range(i + 1, len(pubsubs))
        ]
        await _wait_topic_ready(pubsubs, topic, edges)

        # Publish multiple messages in rapid succession
        num_messages = 10
        messages = [f"rapid_message_{i}".encode() for i in range(num_messages)]
        for message_data in messages:
            await pubsubs[0].publish(topic, message_data)

        # We don't expect perfect delivery under high load — require >= 70%.
        min_needed = int(num_messages * 0.7)
        expected = set(messages)

        async def _wait_peer_enough(sub, peer_index: int) -> None:
            got: set[bytes] = set()
            try:
                with trio.fail_after(10.0):
                    async for msg in sub:
                        if msg.data in expected:
                            got.add(msg.data)
                            if len(got) >= min_needed:
                                return
            except trio.TooSlowError as exc:
                raise AssertionError(
                    f"Peer {peer_index} received too few high-frequency messages "
                    f"(need >= {min_needed}/{num_messages}, got {len(got)})"
                ) from exc

        async with trio.open_nursery() as nursery:
            for i, sub in enumerate(subs, start=1):
                nursery.start_soon(_wait_peer_enough, sub, i)

        # Stop pubsub delivery before factory teardown so late messages cannot
        # schedule push_msg on an already-closing Swarm nursery.
        for ps in pubsubs:
            await ps.unsubscribe(topic)

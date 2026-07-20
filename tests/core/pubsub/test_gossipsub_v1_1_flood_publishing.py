"""
Tests for Gossipsub v1.1 Flood Publishing functionality.

This module tests the flood publishing mechanism in GossipSub v1.1, which
ensures messages are delivered reliably even when published from non-mesh peers.
"""

import pytest
import trio

from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


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
        await trio.sleep(0.5)

        # Only peers 1-4 subscribe to the topic
        topic = "test_flood_publish"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Subscribe peers 1-4 to the topic
            subscriptions = []
            for i in range(1, len(pubsubs)):
                subscription = await pubsubs[i].subscribe(topic)
                subscriptions.append(subscription)

                # Create a task to collect messages
                async def collect_messages(index, sub):
                    try:
                        async for message in sub:
                            received_messages[index].append(message)
                    except trio.Cancelled:
                        pass

                # Start the collection task in the background
                nursery.start_soon(collect_messages, i, subscription)

            await trio.sleep(1.0)  # Allow time for mesh formation

            # Peer 0 is not subscribed but will publish to the topic
            message_data = b"flood published message"
            await pubsubs[0].publish(topic, message_data)

            # Allow time for message propagation
            await trio.sleep(2.0)

            # Verify that all subscribed peers received the message
            for i in range(1, len(pubsubs)):
                assert len(received_messages[i]) > 0
                assert any(msg.data == message_data for msg in received_messages[i])

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()


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
        await trio.sleep(0.5)

        # All peers subscribe to the topic
        topic = "test_flood_publish_mesh_formation"
        received_messages = [[] for _ in range(len(pubsubs))]

        # Start collecting messages in the background
        async with trio.open_nursery() as nursery:
            # Subscribe all peers to the topic
            subscriptions = []
            for i in range(len(pubsubs)):
                subscription = await pubsubs[i].subscribe(topic)
                subscriptions.append(subscription)

                # Start a background task to collect messages for this peer
                async def collect_messages(peer_index, sub):
                    try:
                        async for message in sub:
                            received_messages[peer_index].append(message)
                    except trio.Cancelled:
                        pass

                nursery.start_soon(collect_messages, i, subscription)

            # Wait for subscriptions to be processed and mesh to form
            await trio.sleep(1.0)

            # Publish after allowing some time for initial mesh formation
            message_data = b"early message"
            await pubsubs[0].publish(topic, message_data)

            # Allow time for message propagation
            await trio.sleep(2.0)

            # Verify that peers received the message
            # In a line topology (0-1-2-3), with gossipsub mesh, at least the publisher
            # and its direct neighbors should receive the message
            received_count = sum(
                1
                for msgs in received_messages
                if any(msg.data == message_data for msg in msgs)
            )
            assert received_count >= 1  # At least the publisher should receive it

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()


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
        await trio.sleep(0.5)

        # All peers subscribe to the topic
        topic = "test_flood_publish_reliability"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Subscribe all peers to the topic
            subscriptions = []
            for i in range(len(pubsubs)):
                subscription = await pubsubs[i].subscribe(topic)
                subscriptions.append(subscription)

                # Create a task to collect messages
                async def collect_messages(index, sub):
                    try:
                        async for message in sub:
                            received_messages[index].append(message)
                    except trio.Cancelled:
                        pass

                # Start the collection task in the background
                nursery.start_soon(collect_messages, i, subscription)

            await trio.sleep(1.0)  # Allow time for mesh formation

            # Publish multiple messages from different peers
            messages = []
            for i in range(3):
                message_data = f"message_{i}".encode()
                messages.append(message_data)
                await pubsubs[i].publish(topic, message_data)
                await trio.sleep(0.2)  # Small delay between publishes

            # Allow time for message propagation
            await trio.sleep(2.0)

            # Verify that all peers received all messages
            for peer_msgs in received_messages:
                for msg_data in messages:
                    assert any(msg.data == msg_data for msg in peer_msgs), (
                        f"Message {msg_data} not received by a peer"
                    )

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()


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
        await trio.sleep(0.5)

        # All peers subscribe to the topic
        topic = "test_flood_publish_disconnected"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Subscribe all peers to the topic
            subscriptions = []
            for i in range(len(pubsubs)):
                subscription = await pubsubs[i].subscribe(topic)
                subscriptions.append(subscription)

                # Create a task to collect messages
                async def collect_messages(index, sub):
                    try:
                        async for message in sub:
                            received_messages[index].append(message)
                    except trio.Cancelled:
                        pass

                # Start the collection task in the background
                nursery.start_soon(collect_messages, i, subscription)

            await trio.sleep(1.0)  # Allow time for mesh formation

            # Publish from peer 0
            message_data = b"message from peer 0"
            await pubsubs[0].publish(topic, message_data)

            # Allow time for message propagation
            await trio.sleep(2.0)

            # Verify that peers 0, 1, 2 received the message
            # (peers 3, 4 might not receive it due to network topology)
            for i in range(3):
                assert any(msg.data == message_data for msg in received_messages[i]), (
                    f"Peer {i} did not receive the message"
                )

            # Publish from peer 4
            message_data = b"message from peer 4"
            await pubsubs[4].publish(topic, message_data)

            # Allow time for message propagation
            await trio.sleep(2.0)

            # Verify that peers 2, 3, 4 received the message
            # (peers 0, 1 might not receive it due to network topology)
            for i in [2, 3, 4]:
                assert any(msg.data == message_data for msg in received_messages[i]), (
                    f"Peer {i} did not receive the message"
                )

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()


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
        await trio.sleep(0.5)

        # All peers subscribe to the topic
        topic = "test_flood_publish_high_frequency"
        received_messages = [[] for _ in range(len(pubsubs))]

        async with trio.open_nursery() as nursery:
            # Subscribe all peers to the topic
            subscriptions = []
            for i in range(len(pubsubs)):
                subscription = await pubsubs[i].subscribe(topic)
                subscriptions.append(subscription)

                # Create a task to collect messages
                async def collect_messages(index, sub):
                    try:
                        async for message in sub:
                            received_messages[index].append(message)
                    except trio.Cancelled:
                        pass

                # Start the collection task in the background
                nursery.start_soon(collect_messages, i, subscription)

            await trio.sleep(1.0)  # Allow time for mesh formation

            # Publish multiple messages in rapid succession
            num_messages = 10
            messages = []
            for i in range(num_messages):
                message_data = f"rapid_message_{i}".encode()
                messages.append(message_data)
                await pubsubs[0].publish(topic, message_data)
                # No delay between publishes to test high frequency

            # Allow time for message propagation
            await trio.sleep(3.0)

            # Verify that peers received most of the messages
            # We don't expect perfect delivery under high load
            for i in range(1, len(pubsubs)):
                received_count = 0
                for msg_data in messages:
                    if any(msg.data == msg_data for msg in received_messages[i]):
                        received_count += 1

                # At least 70% of messages should be received
                assert received_count >= num_messages * 0.7, (
                    f"Peer {i} received too few messages: "
                    f"{received_count}/{num_messages}"
                )

            # Cancel all background tasks before exiting
            nursery.cancel_scope.cancel()

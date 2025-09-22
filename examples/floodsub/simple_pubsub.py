#!/usr/bin/env python3
"""
Simple FloodSub PubSub Example

This example demonstrates basic FloodSub functionality:
- Creating a libp2p host with FloodSub
- Publishing messages to topics
- Subscribing to topics and receiving messages
- Basic peer discovery and connection

Run this example with:
    python examples/floodsub/simple_pubsub.py

The example will:
1. Create two libp2p hosts with FloodSub
2. Connect them together
3. Have one host subscribe to a topic
4. Have the other host publish messages to that topic
5. Show the received messages
"""

import logging
import sys

import trio

from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("floodsub_example")


async def publisher_node(pubsub, topic: str, messages: list[str]) -> None:
    """Node that publishes messages to a topic."""
    logger.info(f"Publisher node {pubsub.host.get_id()} starting...")

    # Wait a bit for connections to establish
    await trio.sleep(1)

    # Publish messages
    for i, message in enumerate(messages):
        logger.info(f"Publishing message {i + 1}: {message}")
        await pubsub.publish(topic, message.encode())
        await trio.sleep(0.5)  # Small delay between messages

    logger.info("Publisher finished sending messages")


async def subscriber_node(pubsub, topic: str) -> None:
    """Node that subscribes to a topic and receives messages."""
    logger.info(f"Subscriber node {pubsub.host.get_id()} starting...")

    # Subscribe to the topic
    logger.info(f"Subscribing to topic: {topic}")
    subscription = await pubsub.subscribe(topic)

    # Wait a bit for subscription to propagate
    await trio.sleep(0.5)

    # Receive messages
    received_count = 0
    try:
        while received_count < 3:  # Expect 3 messages
            message = await subscription.get()
            received_count += 1
            logger.info(f"Received message {received_count}: {message.data.decode()}")
            logger.info(f"  From peer: {message.from_id.hex()}")
            logger.info(f"  Topics: {message.topicIDs}")
    except Exception as e:
        logger.error(f"Error receiving message: {e}")

    logger.info("Subscriber finished receiving messages")


async def main() -> None:
    """Main function demonstrating FloodSub pubsub."""
    logger.info("Starting FloodSub PubSub example...")

    topic = "test-topic"
    messages = [
        "Hello from FloodSub!",
        "This is message number 2",
        "FloodSub is working great!",
    ]

    # Create two hosts with FloodSub using the factory
    async with PubsubFactory.create_batch_with_floodsub(2) as pubsubs:
        pubsub1, pubsub2 = pubsubs

        # Get the addresses of both hosts
        addr1 = (
            f"/ip4/127.0.0.1/tcp/{pubsub1.host.get_addrs()[0].split('/')[-1]}/"
            f"p2p/{pubsub1.host.get_id()}"
        )
        addr2 = (
            f"/ip4/127.0.0.1/tcp/{pubsub2.host.get_addrs()[0].split('/')[-1]}/"
            f"p2p/{pubsub2.host.get_id()}"
        )

        logger.info(f"Host 1 address: {addr1}")
        logger.info(f"Host 2 address: {addr2}")

        # Connect the hosts
        logger.info("Connecting hosts...")
        await connect(pubsub1.host, pubsub2.host)
        await trio.sleep(1)  # Wait for connection to establish

        # Run publisher and subscriber concurrently
        async with trio.open_nursery() as nursery:
            # Start subscriber first
            nursery.start_soon(subscriber_node, pubsub2, topic)

            # Start publisher
            nursery.start_soon(publisher_node, pubsub1, topic, messages)

    logger.info("FloodSub example completed successfully!")


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        logger.info("Example interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Example failed: {e}")
        sys.exit(1)

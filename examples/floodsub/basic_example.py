#!/usr/bin/env python3
"""
Basic FloodSub Example

This is a simple example that demonstrates FloodSub publishing and subscribing
without relying on test utilities. It shows the core functionality.

Run this example with:
    python examples/floodsub/basic_example.py
"""

import logging
import sys

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.constants import FLOODSUB_PROTOCOL_ID

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("floodsub_basic")


async def main() -> None:
    """Main function demonstrating basic FloodSub functionality."""
    logger.info("Starting basic FloodSub example...")

    # Create two hosts
    key_pair1 = create_new_key_pair()
    key_pair2 = create_new_key_pair()

    host1 = new_host(
        key_pair=key_pair1,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    host2 = new_host(
        key_pair=key_pair2,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Create FloodSub routers
    floodsub1 = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])
    floodsub2 = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])

    # Create Pubsub instances
    pubsub1 = Pubsub(
        host=host1,
        router=floodsub1,
        strict_signing=False,  # Disable for simplicity
    )

    pubsub2 = Pubsub(
        host=host2,
        router=floodsub2,
        strict_signing=False,  # Disable for simplicity
    )

    # Start both pubsub services with a cancellation scope
    async with trio.open_nursery() as nursery:
        nursery.start_soon(pubsub1.run)
        nursery.start_soon(pubsub2.run)

        # Give services time to start
        await trio.sleep(0.5)
        await pubsub1.wait_until_ready()
        await pubsub2.wait_until_ready()

        logger.info(f"Host 1 ID: {host1.get_id()}")
        logger.info(f"Host 2 ID: {host2.get_id()}")

        # Start listening on both hosts
        logger.info("Starting hosts...")
        await host1.get_network().listen()
        await host2.get_network().listen()
        await trio.sleep(0.5)  # Wait for hosts to start listening

        # Connect the hosts with timeout
        logger.info("Connecting hosts...")
        peer_info = PeerInfo(host2.get_id(), host2.get_addrs())
        try:
            with trio.move_on_after(5):  # 5 second timeout for connection
                await host1.connect(peer_info)
                logger.info("Hosts connected successfully")
        except trio.TooSlowError:
            logger.error("Connection timed out")
            nursery.cancel_scope.cancel()
            return

        await trio.sleep(1)  # Wait for connection to establish

        # Subscribe to topic on host2
        topic = "test-topic"
        logger.info(f"Subscribing to topic: {topic}")
        subscription = await pubsub2.subscribe(topic)
        await trio.sleep(0.5)  # Wait for subscription to propagate

        # Publish messages from host1
        messages = [
            "Hello from FloodSub!",
            "This is message number 2",
            "FloodSub is working great!",
        ]

        logger.info("Publishing messages...")
        for i, message in enumerate(messages):
            logger.info(f"Publishing message {i + 1}: {message}")
            await pubsub1.publish(topic, message.encode())
            await trio.sleep(0.5)

        # Receive messages on host2 with timeout
        logger.info("Receiving messages...")
        received_count = 0
        for i in range(len(messages)):
            # Use a timeout to prevent hanging
            with trio.move_on_after(3) as cancel_scope:  # Reduced timeout
                message = await subscription.get()
                logger.info(f"Received message {i + 1}: {message.data.decode()}")
                logger.info(f"  From peer: {message.from_id.hex()}")
                logger.info(f"  Topics: {message.topicIDs}")
                received_count += 1

            if cancel_scope.cancelled_caught:
                logger.warning(f"Timed out waiting for message {i + 1}")
                break

        logger.info(
            f"Successfully received {received_count} out of {len(messages)} messages"
        )

        # Clean up by cancelling the nursery
        nursery.cancel_scope.cancel()

    logger.info("Basic FloodSub example completed successfully!")


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        logger.info("Example interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Example failed: {e}")
        sys.exit(1)

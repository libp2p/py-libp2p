#!/usr/bin/env python3
"""
Multi-Node FloodSub PubSub Example

This example demonstrates FloodSub with multiple nodes:
- Creates 3 libp2p hosts with FloodSub
- Connects them in a simple network topology
- Demonstrates publishing and subscribing to multiple topics
- Shows message flooding across the network

Run this example with:
    python examples/floodsub/multi_node_pubsub.py

The example will:
1. Create 3 libp2p hosts with FloodSub
2. Connect them in a chain: A -> B -> C
3. Have different nodes subscribe to different topics
4. Publish messages from different nodes
5. Show how messages flood through the network
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import functools
import logging
import sys
from typing import Any

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import PeerInfo
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.constants import FLOODSUB_PROTOCOL_ID

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multi_node_floodsub")


@asynccontextmanager
async def create_floodsub_host() -> AsyncGenerator[tuple[IHost, Pubsub], None]:
    """Create a libp2p host with FloodSub pubsub router."""
    # Generate a private key for the host
    key_pair = create_new_key_pair()

    # Create the host
    host = new_host(
        key_pair=key_pair,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Create FloodSub router
    floodsub = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])

    # Create Pubsub instance with FloodSub
    pubsub = Pubsub(
        host=host,
        router=floodsub,
        strict_signing=False,  # Disable strict signing for simplicity
    )

    # Start the pubsub service
    async with background_trio_service(pubsub):
        await pubsub.wait_until_ready()
        yield host, pubsub


async def node_worker(
    host: IHost,
    pubsub: Pubsub,
    node_name: str,
    subscriptions: list[str],
    publications: list[tuple[str, str]],
) -> None:
    """Worker function for a node that can both subscribe and publish."""
    logger.info(f"Node {node_name} ({host.get_id()}) starting...")

    # Wait for connections to establish
    await trio.sleep(2)

    # Subscribe to topics
    subscriptions_handles = []
    for topic in subscriptions:
        logger.info(f"Node {node_name} subscribing to topic: {topic}")
        subscription = await pubsub.subscribe(topic)
        subscriptions_handles.append((topic, subscription))

    # Wait for subscriptions to propagate
    await trio.sleep(1)

    # Start receiving messages in background
    async def receive_messages() -> None:
        for topic, subscription in subscriptions_handles:
            try:
                while True:
                    message = await subscription.get()
                    logger.info(
                        f"Node {node_name} received on {topic}: {message.data.decode()}"
                    )
                    logger.info(f"  From: {message.from_id.hex()[:8]}...")
            except Exception as e:
                logger.error(f"Node {node_name} error receiving from {topic}: {e}")

    # Start message receiving
    async with trio.open_nursery() as nursery:
        nursery.start_soon(receive_messages)

        # Publish messages
        for topic, message in publications:
            logger.info(f"Node {node_name} publishing to {topic}: {message}")
            await pubsub.publish(topic, message.encode())
            await trio.sleep(1)  # Delay between publications

        # Keep running to receive messages
        await trio.sleep(5)


async def main() -> None:
    """Main function demonstrating multi-node FloodSub pubsub."""
    logger.info("Starting Multi-Node FloodSub PubSub example...")

    # Define topics and messages (used for reference)
    # topics = ["news", "chat", "updates"]

    # Create 3 hosts
    async with create_floodsub_host() as (host1, pubsub1):
        async with create_floodsub_host() as (host2, pubsub2):
            async with create_floodsub_host() as (host3, pubsub3):
                # Get addresses
                addr1 = (
                    f"/ip4/127.0.0.1/tcp/{str(host1.get_addrs()[0]).split('/')[-1]}/"
                    f"p2p/{host1.get_id()}"
                )
                addr2 = (
                    f"/ip4/127.0.0.1/tcp/{str(host2.get_addrs()[0]).split('/')[-1]}/"
                    f"p2p/{host2.get_id()}"
                )
                addr3 = (
                    f"/ip4/127.0.0.1/tcp/{str(host3.get_addrs()[0]).split('/')[-1]}/"
                    f"p2p/{host3.get_id()}"
                )

                logger.info(f"Node A address: {addr1}")
                logger.info(f"Node B address: {addr2}")
                logger.info(f"Node C address: {addr3}")

                # Connect nodes in a chain: A -> B -> C
                logger.info("Connecting nodes...")
                peer_info2 = PeerInfo(host2.get_id(), host2.get_addrs())
                await host1.connect(peer_info2)
                peer_info3 = PeerInfo(host3.get_id(), host3.get_addrs())
                await host2.connect(peer_info3)
                await trio.sleep(2)  # Wait for connections to establish

                # Define node behaviors
                node_configs: list[dict[str, Any]] = [
                    {
                        "name": "A",
                        "host": host1,
                        "pubsub": pubsub1,
                        "subscriptions": ["news", "chat"],
                        "publications": [
                            ("news", "Breaking: FloodSub is working!"),
                            ("updates", "Update from Node A"),
                        ],
                    },
                    {
                        "name": "B",
                        "host": host2,
                        "pubsub": pubsub2,
                        "subscriptions": ["news", "updates"],
                        "publications": [
                            ("chat", "Hello from Node B!"),
                            ("news", "News from Node B"),
                        ],
                    },
                    {
                        "name": "C",
                        "host": host3,
                        "pubsub": pubsub3,
                        "subscriptions": ["chat", "updates"],
                        "publications": [
                            ("updates", "Update from Node C"),
                            ("chat", "Chat message from Node C"),
                        ],
                    },
                ]

                # Run all nodes concurrently
                async with trio.open_nursery() as nursery:
                    for config in node_configs:
                        worker_func = functools.partial(
                            node_worker,
                            config["host"],  # type: ignore[arg-type]
                            config["pubsub"],  # type: ignore[arg-type]
                            config["name"],  # type: ignore[arg-type]
                            config["subscriptions"],  # type: ignore[arg-type]
                            config["publications"],  # type: ignore[arg-type]
                        )
                        nursery.start_soon(worker_func)

    logger.info("Multi-Node FloodSub example completed successfully!")


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        logger.info("Example interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Example failed: {e}")
        sys.exit(1)

#!/usr/bin/env python

"""
A basic example of using the Kademlia DHT implementation, with all setup logic inlined.
This example demonstrates both value storage/retrieval and content provider
advertisement/discovery.
"""

import argparse
import hashlib
import json
import logging
import os
import random
import secrets
import sys
from typing import (
    Any,
    Optional,
)

import base58
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.kad_dht.kad_dht import (
    KadDHT,
)
from libp2p.kad_dht.utils import (
    create_key_from_binary,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.tools.async_service import (
    background_trio_service,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("kademlia.log"), logging.StreamHandler()],
)
logger = logging.getLogger("kademlia-example")

# File to store node information
NODE_INFO_FILE = "dht_node_info.json"
PROTOCOL_ID = "/ipfs/kad/1.0.0"


def save_node_info(port: int, peer_id: str) -> None:
    """Save node information to a file for later use."""
    info = {"port": port, "peer_id": peer_id}

    with open(NODE_INFO_FILE, "w") as f:
        json.dump(info, f)

    logger.info(f"Saved node info to {NODE_INFO_FILE}")


def load_node_info() -> Optional[dict[str, Any]]:
    """Load node information from file if available."""
    if not os.path.exists(NODE_INFO_FILE):
        return None

    try:
        with open(NODE_INFO_FILE) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load node info: {e}")
        return None


def calculate_content_id(content: bytes) -> bytes:
    """
    Calculate a multihash-style content ID for a piece of content.
    This emulates the IPFS CID but much simplified for the example.

    Args:
        content: The content bytes

    Returns
    -------
        bytes: A SHA-256 multihash of the content

    """
    # Get the SHA-256 hash
    content_hash = hashlib.sha256(content).digest()
    # For simplicity, we use the raw hash as the key
    return content_hash


async def run_provider_node(
    port: int, bootstrap_addrs: Optional[list[str]] = None
) -> None:
    """Run a node that provides content in the DHT with setup inlined."""
    try:
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

        async with host.run(listen_addrs=[listen_addr]):
            peer_id = host.get_id().pretty()
            addr_str = f"/ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}"
            logger.info(f"Node listening on: {addr_str}")
            save_node_info(port, peer_id)
            logger.info("Node info saved")
            bootstrap_peers = []
            if bootstrap_addrs:
                for addr in bootstrap_addrs:
                    try:
                        peer_info = info_from_p2p_addr(Multiaddr(addr))
                        bootstrap_peers.append(peer_info)
                        logger.info(f"Using bootstrap node: {addr}")
                    except Exception as e:
                        logger.error(f"Failed to parse bootstrap address: {e}")
                        raise
            print("Bootstrap peers:", bootstrap_peers)
            dht = KadDHT(host, bootstrap_peers)
            print("Starting DHT service...")
            logger.info("Starting DHT service...")

            # Start the DHT service
            async with background_trio_service(dht):
                await trio.sleep(0.1)
                logger.info("DHT service started")

                # If we have bootstrap nodes, connect to them
                if bootstrap_peers:
                    for bootstrap_info in bootstrap_peers:
                        try:
                            await dht.host.connect(bootstrap_info)
                            logger.info(
                                "Connected to bootstrap node: %s",
                                bootstrap_info.peer_id.pretty(),
                            )
                        except Exception as e:
                            logger.error(f"Failed to connect to bootstrap node: {e}")

                # Store a value in the DHT
                val_key = create_key_from_binary(b"example-key")
                # Build value data
                msg = f"This is an example value at {trio.current_time()}"
                val_data = msg.encode()
                logger.info(
                    f"Storing value with key: {base58.b58encode(val_key).decode()}"
                )
                await dht.put_value(val_key, val_data)
                logger.info(
                    f"Stored value with key: {base58.b58encode(val_key).decode()}"
                )

                # Create a piece of content and advertise as provider
                content = b"Hello from provider node "
                content_key = calculate_content_id(content)
                logger.info(f"Generated content with ID: {content_key.hex()}")

                # Advertise that we can provide this content
                logger.info(f"Advertising as provider for content: {content_key.hex()}")
                success = await dht.provide(content_key)
                if success:
                    logger.info("Successfully advertised as content provider")
                else:
                    logger.warning("Failed to advertise as content provider")

                # Also check if we can find providers for our own content
                content_key = (
                    "25e19514a354bac2413dc71f5f8e0b974577cd07663ca02d8715ac2a6d110460"
                )
                logger.info("Looking for providers of content: %s", content_key)
                # Convert hex content ID to bytes
                content_key = bytes.fromhex(content_key)
                logger.info("Looking for providers of content1: %s", content_key.hex())
                # bytes to string
                content_key = content_key.decode()
                logger.info("decoded content key is: %s", content_key)
                providers = await dht.find_providers(content_key)
                if providers:
                    logger.info(
                        "Found %d providers for our content: %s",
                        len(providers),
                        [p.peer_id.pretty() for p in providers],
                    )
                else:
                    logger.warning(
                        "No providers found for our content %s", content_key.hex()
                    )

                # Print bootstrap command for consumer nodes
                bootstrap_cmd = f"--bootstrap {addr_str}"
                logger.info("To connect to this node, use: %s", bootstrap_cmd)
                print(f"\nTo connect to this node, use: {bootstrap_cmd}\n")
                print(f"Content ID for discovery: {content_key.hex()}")

                # Keep the node running
                while True:
                    logger.info(
                        "Provider running with %d peers", dht.get_routing_table_size()
                    )
                    logger.info(
                        "Peers in Routing table are: %s",
                        dht.routing_table.get_peer_ids(),
                    )
                    logger.info(
                        "Peer store size: %s", dht.host.get_peerstore().peer_ids()
                    )
                    logger.info("Value store contains: %s", dht.value_store.store)
                    logger.info(
                        "Provider store contains: %s", str(dht.provider_store.providers)
                    )
                    logger.info(
                        "Provider store size: %s", str(dht.provider_store.size())
                    )

                    # Display content provider information
                    for key in dht.provider_store.providers:
                        providers = dht.provider_store.get_providers(key)
                        logger.info(
                            "Key %s is provided by %s",
                            key.hex(),
                            [p.peer_id for p in providers],
                        )

                    await trio.sleep(100)

    except Exception as e:
        logger.error(f"Provider node error: {e}", exc_info=True)
        sys.exit(1)


async def run_consumer_node(
    port: int, bootstrap_addrs: list[str], content_id: Optional[str] = None
) -> None:
    """Run a node that consumes content from the DHT with setup inlined."""
    try:
        # Validate bootstrap addresses
        bootstrap_peers = []
        for addr in bootstrap_addrs:
            try:
                peer_info = info_from_p2p_addr(Multiaddr(addr))
                bootstrap_peers.append(peer_info)
                logger.info(f"Using bootstrap node: {peer_info.peer_id.pretty()}")
            except Exception as e:
                logger.error(f"Failed to parse bootstrap address: {e}")
                raise

        # === Inlined setup_dht_node logic ===
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

        # Start the host
        async with host.run(listen_addrs=[listen_addr]):
            await host.get_network().listen(listen_addr)
            logger.info("Host running successfully")
            peer_id = host.get_id().pretty()
            addr_str = f"/ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}"
            logger.info(f"Node listening on: {addr_str}")
            save_node_info(port, peer_id)

            dht = KadDHT(host, bootstrap_peers)
            # ====================================
            logger.info("Starting DHT service...")
            # Start the DHT service
            async with background_trio_service(dht):
                await trio.sleep(1)

                # Connect to the bootstrap nodes
                for bootstrap_info in bootstrap_peers:
                    try:
                        await dht.host.connect(bootstrap_info)
                        logger.info(
                            "Connected to bootstrap node: %s",
                            bootstrap_info.peer_id.pretty(),
                        )
                    except Exception as e:
                        logger.error(f"Failed to connect to bootstrap node: {e}")
                        sys.exit(1)

                # Store a value in the DHT
                val_key = create_key_from_binary(b"example-key")
                # Prepare consumer value data
                msg = f"This is a value from consumer node at {trio.current_time()}"
                val_data = msg.encode()
                logger.info(
                    "Storing value with key: %s", base58.b58encode(val_key).decode()
                )
                await dht.put_value(val_key, val_data)
                logger.info(
                    "Stored value with key: %s", base58.b58encode(val_key).decode()
                )

                # Wait for the DHT to bootstrap
                await trio.sleep(3)

                # Try to retrieve the value
                # Lookup the stored key
                key_str = base58.b58encode(val_key).decode()
                logger.info("Looking up key: %s", key_str)
                value = await dht.get_value(val_key)
                if value:
                    logger.info(f"Retrieved value: {value.decode()}")
                    print(f"Retrieved value: {value.decode()}")
                else:
                    logger.warning("Failed to retrieve value")

                # If content ID was provided, try to find providers
                if content_id:
                    try:
                        # Convert hex content ID to bytes
                        content_key = bytes.fromhex(content_id)
                        logger.info(f"Looking for providers of content: {content_id}")

                        # Find providers for this content
                        providers = await dht.find_providers(content_key)
                        if providers:
                            logger.info(
                                "Found %d providers for content %s",
                                len(providers),
                                content_id,
                            )
                            for provider in providers:
                                logger.info(
                                    f"Content provider: {provider.peer_id.pretty()}"
                                )
                                logger.info(f"Provider addresses: {provider.addrs}")
                                print(
                                    f"Found content provider: "
                                    f"{provider.peer_id.pretty()} at addresses:"
                                )
                                for addr in provider.addrs:
                                    print(f"  - {addr}")
                        else:
                            logger.warning(
                                f"No providers found for content {content_id}"
                            )
                            print(f"No providers found for content {content_id}")
                    except Exception as e:
                        logger.error(f"Error finding content providers: {e}")

                # Keep the node running
                while True:
                    logger.info(
                        "Consumer running with %d peers", dht.get_routing_table_size()
                    )
                    logger.info(
                        "Peer store size: %s", dht.host.get_peerstore().peer_ids()
                    )

                    # Check if we have new provider records
                    if content_id:
                        content_key = bytes.fromhex(content_id)
                        local_providers = dht.provider_store.get_providers(content_key)
                        if local_providers:
                            logger.info(
                                "Locally known providers for %s: %s",
                                content_id,
                                [p.peer_id.pretty() for p in local_providers],
                            )

                    await trio.sleep(30)

    except Exception as e:
        logger.error(f"Consumer node error: {e}", exc_info=True)
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kademlia DHT example with content provider functionality"
    )
    parser.add_argument(
        "--mode",
        choices=["provider", "consumer"],
        required=True,
        help="Run as a provider or consumer node",
    )
    parser.add_argument(
        "--port", type=int, default=0, help="Port to listen on (0 for random)"
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help=(
            "Multiaddrs of bootstrap nodes. "
            "Provide a space-separated list of addresses. "
            "This is required for consumer mode."
        ),
    )
    parser.add_argument(
        "--use-saved",
        action="store_true",
        help="Use saved node info for bootstrap (consumer mode only)",
    )
    parser.add_argument(
        "--content-id",
        type=str,
        help="Hex-encoded content ID to look for providers (consumer mode only)",
    )

    args = parser.parse_args()

    # Handle using saved node info
    if args.use_saved and args.mode == "consumer":
        node_info = load_node_info()
        if node_info:
            saved_addr = (
                f"/ip4/127.0.0.1/tcp/{node_info['port']}/p2p/{node_info['peer_id']}"
            )
            if args.bootstrap is None:
                args.bootstrap = []
            args.bootstrap.append(saved_addr)
            logger.info("Using saved bootstrap address:")
            logger.info(f"  - {saved_addr}")

    if args.mode == "consumer" and (not args.bootstrap or len(args.bootstrap) == 0):
        parser.error(
            "Consumer mode requires at least one"
            " bootstrap address (use --bootstrap or --use-saved)"
        )

    # Use random port if not specified
    if args.port == 0:
        args.port = random.randint(10000, 60000)
        logger.info(f"Using random port: {args.port}")

    return args


if __name__ == "__main__":
    try:
        args = parse_args()
        logger.info(
            "Running in %s mode on port %d",
            args.mode,
            args.port,
        )

        if args.mode == "provider":
            trio.run(run_provider_node, args.port, args.bootstrap)
        else:
            trio.run(run_consumer_node, args.port, args.bootstrap, args.content_id)
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)

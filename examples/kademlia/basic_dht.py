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
from libp2p.tools.async_service import (
    background_trio_service,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("kademlia-example")

# Configure DHT module loggers to inherit from the parent logger
# This ensures all kademlia-example.* loggers use the same configuration
kad_logger = logging.getLogger("kademlia-example")
kad_logger.setLevel(logging.INFO)

# Set the level for all child loggers
for module in [
    "kad_dht",
    "value_store",
    "peer_routing",
    "routing_table",
    "provider_store",
]:
    child_logger = logging.getLogger(f"kademlia-example.{module}")
    child_logger.setLevel(logging.INFO)
    child_logger.propagate = True  # Allow propagation to parent

# File to store node information
NODE_INFO_FILE = "dht_node_info.json"
bootstrap_nodes = [
    # "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
    # "/ip4/145.40.118.135/tcp/4001/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
    # "/ip4/147.75.87.27/tcp/4001/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    # "/ip4/139.178.91.71/tcp/4001/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    # "/ip4/139.178.65.157/tcp/4001/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/ip4/127.0.0.1/tcp/48233/p2p/16Uiu2HAmCrXHNdLeB4qHA5WsEtiJfH85DZZhU4mdw2BecwQk1Z6S"
]


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
        bootstrap_addrs = bootstrap_nodes
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

        async with host.run(listen_addrs=[listen_addr]):
            peer_id = host.get_id().pretty()
            addr_str = f"/ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}"
            logger.info(f"Node listening on: {addr_str}")
            logger.info("Node info saved")
            print("Bootstrap peers:", bootstrap_addrs)
            dht = KadDHT(host, bootstrap_addrs)
            print("Starting DHT service...")
            logger.info("Starting DHT service...")

            # Start the DHT service
            async with background_trio_service(dht):
                await trio.sleep(1)
                logger.info("DHT service started")

                # Store a value in the DHT
                val_key = create_key_from_binary(b"py-libp2p kademlia example value")
                msg = "Hello message from Sumanjeet"
                val_data = msg.encode()
                logger.info(
                    f"Storing value with key: {base58.b58encode(val_key).decode()}"
                )
                await dht.put_value(val_key, val_data)
                logger.info(
                    f"Stored value with key: {base58.b58encode(val_key).decode()}"
                )
                logger.info("Value stored is %s", val_data.decode())
                trio.sleep(0.5)

                # retrieve the value
                logger.info("Looking up key: %s", base58.b58encode(val_key).decode())
                val_data = await dht.get_value(val_key)
                if val_data:
                    try:
                        logger.info(f"Retrieved value: {val_data.hex()}")
                    except UnicodeDecodeError:
                        logger.info(f"Retrieved value (bytes): {val_data!r}")
                else:
                    logger.warning("Failed to retrieve value")

                # # Create a piece of content and advertise as provider
                content = b"Hello from python node "
                content_key = create_key_from_binary(content)
                logger.info(f"Generated content with ID: {content_key.hex()}")
                # Advertise that we can provide this content
                logger.info(
                    "Advertising as provider for content:" f" {content_key.hex()}"
                )
                success = await dht.provider_store.provide(content_key)
                if success:
                    logger.info("Successfully advertised as content provider")
                else:
                    logger.warning("Failed to advertise as content provider")

                # # Also check if we can find providers for our own content
                logger.info("Looking for providers of content: %s", content_key.hex())
                providers = await dht.provider_store.find_providers(content_key)
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
                # print(f"Content ID for discovery: {content_key.hex()}")

                # Keep the node running
                while True:
                    logger.info(
                        "connected peers are %s", dht.host.get_connected_peers()
                    )
                    logger.info(
                        "Number of peers in peer store are %s",
                        len(dht.host.get_peerstore().peer_ids()),
                    )
                    logger.info(f"values in value store: {dht.value_store.store}")

                    await trio.sleep(10)

    except Exception as e:
        logger.error(f"Provider node error: {e}", exc_info=True)
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
    # add option to use verbose logging
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    # Set logging level based on verbosity
    if parser.parse_args().verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

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
        # else:
        #     trio.run(run_consumer_node, args.port, args.bootstrap, args.content_id)
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)

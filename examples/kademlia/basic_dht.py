#!/usr/bin/env python

"""
A basic example of using the Kademlia DHT implementation, with all setup logic inlined.
This example demonstrates both value storage/retrieval and content server
advertisement/discovery.
"""

import argparse
import hashlib
import logging
import os
import random
import secrets
import sys

import base58
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p import (
    new_host,
)
from libp2p.abc import (
    IHost,
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
from libp2p.tools.utils import (
    info_from_p2p_addr,
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
SERVER_ADDR_LOG = "dht_server_addrs.log"

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
bootstrap_nodes = []


# function to take bootstrap_nodes as input and connects to them
async def connect_to_bootstrap_nodes(host: IHost, bootstrap_addrs: list[str]) -> None:
    """
    Connect to the bootstrap nodes provided in the list.

    params: host: The host instance to connect to
            bootstrap_addrs: List of bootstrap node addresses

    Returns
    -------
        None

    """
    for addr in bootstrap_addrs:
        try:
            await trio.sleep(2)
            peerInfo = info_from_p2p_addr(Multiaddr(addr))
            host.get_peerstore().add_addrs(peerInfo.peer_id, peerInfo.addrs, 3600)
            await host.connect(peerInfo)
        except Exception as e:
            logger.error(f"Failed to connect to bootstrap node {addr}: {e}")


def save_server_addr(addr: str) -> None:
    """Append the server's multiaddress to the log file."""
    try:
        with open(SERVER_ADDR_LOG, "w") as f:
            f.write(addr + "\n")
        logger.info(f"Saved server address to log: {addr}")
    except Exception as e:
        logger.error(f"Failed to save server address: {e}")


def load_server_addrs() -> list[str]:
    """Load all server multiaddresses from the log file."""
    if not os.path.exists(SERVER_ADDR_LOG):
        return []
    try:
        with open(SERVER_ADDR_LOG) as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        logger.error(f"Failed to load server addresses: {e}")
        return []


def calculate_content_id(content: bytes) -> bytes:
    """
    Calculate a multihash-style content ID for a piece of content.
    This emulates the IPFS CID but much simplified for the example.

    params: content: The content bytes

    Returns
    -------
        bytes: A SHA-256 multihash of the content

    """
    # Get the SHA-256 hash
    content_hash = hashlib.sha256(content).digest()
    # For simplicity, we use the raw hash as the key
    return content_hash


async def run_node(
    port: int, mode: str, bootstrap_addrs: list[str] | None = None
) -> None:
    """Run a node that serves content in the DHT with setup inlined."""
    try:
        if port <= 0:
            port = random.randint(10000, 60000)
        logger.debug(f"Using port: {port}")
        # Load server addresses for client mode
        if mode.upper() == "CLIENT":
            server_addrs = load_server_addrs()
            if server_addrs:
                logger.info(f"Loaded {len(server_addrs)} server addresses from log")
                bootstrap_nodes.append(server_addrs[0])  # Use the first server address
            else:
                logger.warning("No server addresses found in log file")

        if bootstrap_addrs:
            for addr in bootstrap_addrs:
                bootstrap_nodes.append(addr)

        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)
        listen_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")

        async with host.run(listen_addrs=[listen_addr]):
            peer_id = host.get_id().pretty()
            addr_str = f"/ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}"
            await connect_to_bootstrap_nodes(host, bootstrap_nodes)
            await trio.sleep(3)
            logger.info(
                f"testing connection to bootstrap nodes: {host.get_connected_peers()}"
            )
            dht = KadDHT(host, mode)
            # take all peer ids from the host and add them to the dht
            for peer_id in host.get_peerstore().peer_ids():
                await dht.routing_table.add_peer(peer_id)
            logger.info(f"Connected to bootstrap nodes: {host.get_connected_peers()}")
            logger.debug("Starting DHT service...")
            bootstrap_cmd = f"--bootstrap {addr_str}"
            logger.info("To connect to this node, use: %s", bootstrap_cmd)

            # Save server address in server mode
            if mode.upper() == "SERVER":
                save_server_addr(addr_str)

            # Start the DHT service
            async with background_trio_service(dht):
                await trio.sleep(1)
                logger.info("DHT service started")
                val_key = create_key_from_binary(b"py-libp2p kademlia example value")
                logger.info(
                    f"Generated value key: {base58.b58encode(val_key).decode()}"
                )
                content = b"Hello from python node "
                content_key = create_key_from_binary(content)
                logger.info(f"running in mode: {mode.upper()}")

                if mode.upper() == "SERVER":
                    logger.info("Running in server mode1")
                    # Store a value in the DHT
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
                    await trio.sleep(0.5)

                    # # Create a piece of content and advertise as server
                    logger.info(f"Generated content with ID: {content_key.hex()}")
                    # Advertise that we can serve this content
                    logger.info(
                        f"Advertising as server for content: {content_key.hex()}"
                    )
                    success = await dht.provider_store.provide(content_key)
                    if success:
                        logger.info("Successfully advertised as content server")
                    else:
                        logger.warning("Failed to advertise as content server")

                else:
                    logger.debug("Running in client mode")

                    # retrieve the value
                    logger.info(
                        "Looking up key: %s", base58.b58encode(val_key).decode()
                    )
                    logger.info(
                        "Number of nodes connected:"
                        f"{len(dht.host.get_connected_peers())}"
                    )
                    await trio.sleep(5)
                    val_data = await dht.get_value(val_key)
                    if val_data:
                        try:
                            logger.info(f"Retrieved value: {val_data.hex()}")
                        except UnicodeDecodeError:
                            logger.info(f"Retrieved value (bytes): {val_data!r}")
                    else:
                        logger.warning("Failed to retrieve value")

                    # Also check if we can find servers for our own content
                    logger.info("Looking for servers of content: %s", content_key.hex())
                    providers = await dht.provider_store.find_providers(content_key)
                    if providers:
                        logger.info(
                            "Found %d servers for our content: %s",
                            len(providers),
                            [p.peer_id.pretty() for p in providers],
                        )
                    else:
                        logger.warning(
                            "No servers found for our content %s", content_key.hex()
                        )

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
        logger.error(f"Server node error: {e}", exc_info=True)
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kademlia DHT example with content server functionality"
    )
    parser.add_argument(
        "--mode",
        default="server",
        help="Run as a server or client node",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 for random)",
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help=(
            "Multiaddrs of bootstrap nodes. "
            "Provide a space-separated list of addresses. "
            "This is required for client mode."
        ),
    )
    parser.add_argument(
        "--use-saved",
        action="store_true",
        help="Use saved node info for bootstrap (client mode only)",
    )
    parser.add_argument(
        "--content-id",
        type=str,
        help="Hex-encoded content ID to look for servers (client mode only)",
    )
    # add option to use verbose logging
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logger.info("Parsed arguments: %s", args)

    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    return args


if __name__ == "__main__":
    try:
        args = parse_args()
        logger.info(
            "Running in %s mode on port %d",
            args.mode,
            args.port,
        )

        trio.run(run_node, args.port, args.mode, args.bootstrap)
        # else:
        #     trio.run(run_client_node, args.port, args.bootstrap, args.content_id)
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)

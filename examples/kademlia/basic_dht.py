
#!/usr/bin/env python

"""
A basic example of using the Kademlia DHT implementation, with all setup logic inlined.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import secrets
import sys
from typing import List, Optional, Dict, Any

import base58
import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import KadDHT
from libp2p.kad_dht.utils import create_key_from_binary
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.tools.async_service import background_trio_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("kademlia.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("kademlia-example")

# File to store node information
NODE_INFO_FILE = "dht_node_info.json"
PROTOCOL_ID = "/ipfs/kad/1.0.0"

def save_node_info(port: int, peer_id: str) -> None:
    """Save node information to a file for later use."""
    info = {
        "port": port,
        "peer_id": peer_id
    }
    
    with open(NODE_INFO_FILE, "w") as f:
        json.dump(info, f)
    
    logger.info(f"Saved node info to {NODE_INFO_FILE}")


def load_node_info() -> Optional[Dict[str, Any]]:
    """Load node information from file if available."""
    if not os.path.exists(NODE_INFO_FILE):
        return None
    
    try:
        with open(NODE_INFO_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load node info: {e}")
        return None


async def run_provider_node(port: int, bootstrap_addrs: Optional[List[str]] = None) -> None:
    """Run a node that provides content in the DHT with setup inlined."""
    try:
        # === Inlined setup_dht_node logic ===
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

        # Start the host
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
            print("Starting DHT service1...")
            logger.info("Starting DHT service...")
        # ====================================

        # Start the DHT service
            async with background_trio_service(dht):
                await trio.sleep(0.1)
                logger.info("DHT service started")
                # If we have bootstrap nodes, connect to them
                if bootstrap_peers:
                    for bootstrap_info in bootstrap_peers:
                        try:
                            await dht.host.connect(bootstrap_info)
                            logger.info(f"Connected to bootstrap node: {bootstrap_info.peer_id.pretty()}")
                        except Exception as e:
                            logger.error(f"Failed to connect to bootstrap node: {e}")

                # Store a value in the DHT
                # val_key = create_key_from_binary(b"example-key")
                # val_data = f"This is an example value at {trio.current_time()}".encode()
                # logger.info(f"Storing value with key: {base58.b58encode(val_key).decode()}")
                # await dht.put_value(val_key, val_data)
                # logger.info(f"Stored value with key: {base58.b58encode(val_key).decode()}")

                # Retrieve the value from the DHT
                val_key = create_key_from_binary(b"example-key")
                logger.info(f"Looking up key: {base58.b58encode(val_key).decode()}")
                value = await dht.get_value(val_key)
                if value:
                    logger.info(f"Retrieved value: {value.decode()}")
                else:
                    logger.warning("Failed to retrieve value")

                # Print bootstrap command for consumer nodes
                bootstrap_cmd = f"--bootstrap {addr_str}"
                logger.info(f"To connect to this node, use: {bootstrap_cmd}")
                print(f"\nTo connect to this node, use: {bootstrap_cmd}\n")

                # Keep the node running
                while True:
                    logger.info(f"Provider running with {dht.get_routing_table_size()} peers")
                    logger.info("Peers in Routing table are: " + str(dht.routing_table.get_peer_ids()))
                    logger.info("Peer store size" + str(dht.host.get_peerstore().peer_ids()))
                    # logger.info("shortest path to peer: " + str(dht.routing_table.find_closest_peers(content_key,20)))
                    logger.info("value store contains: " + str(dht.value_store.store))
                    await trio.sleep(10)

    except Exception as e:
        logger.error(f"Provider node error: {e}", exc_info=True)
        sys.exit(1)


async def run_consumer_node(port: int, bootstrap_addrs: List[str]) -> None:
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
            logger.info("Host running sucessfully")
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
                        stream = await dht.host.new_stream(bootstrap_info.peer_id, [PROTOCOL_ID])
                        await stream.write(b"PING") # Send a ping message
                        await stream.close()
                        logger.info(f"Connected to bootstrap node: {bootstrap_info.peer_id.pretty()}")
                    except Exception as e:
                        logger.error(f"Failed to connect to bootstrap node: {e}")
                        sys.exit(1)

                # Wait for the DHT to bootstrap
                await trio.sleep(3)
                # Try to retrieve the value
                # val_key = create_key_from_binary(b"example-key")
                # logger.info(f"Looking up key: {base58.b58encode(val_key).decode()}")

                # for attempt in range(1, 3):
                #     value = await dht.get_value(val_key)
                #     if value:
                #         logger.info(f"Retrieved value: {value.decode()}")
                #         print(f"Retrieved value: {value.decode()}")
                #         break
                #     logger.info(f"Value not found (attempt {attempt}/2), waiting...")
                #     await trio.sleep(2)
                # else:
                #     logger.warning("Failed to retrieve value")

                content = f"Hello from provider node".encode()
                content_key = create_key_from_binary(content)
                value = await dht.get_value(content_key)
                if value:
                    print(f"Retrieved content: {value}")
                else:
                    logger.warning("Failed to retrieve content")                

                # Keep the node running
                while True:
                    logger.info(f"Consumer running with {dht.get_routing_table_size()} peers")
                    logger.info("Peer store size" + str(dht.host.get_peerstore().peer_ids()))
                    await trio.sleep(30)

    except Exception as e:
        logger.error(f"Consumer node error: {e}", exc_info=True)
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Kademlia DHT example")
    parser.add_argument(
        "--mode", 
        choices=["provider", "consumer"], 
        required=True,
        help="Run as a provider or consumer node"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=0,
        help="Port to listen on (0 for random)"
    )
    parser.add_argument(
        "--bootstrap", 
        type=str,
        nargs="*",
        help="Multiaddrs of bootstrap nodes (space-separated list, required for consumer)"
    )
    parser.add_argument(
        "--use-saved",
        action="store_true",
        help="Use saved node info for bootstrap (consumer mode only)"
    )
    
    args = parser.parse_args()
    
    # Handle using saved node info
    if args.use_saved and args.mode == "consumer":
        node_info = load_node_info()
        if node_info:
            saved_addr = f"/ip4/127.0.0.1/tcp/{node_info['port']}/p2p/{node_info['peer_id']}"
            if args.bootstrap is None:
                args.bootstrap = []
            args.bootstrap.append(saved_addr)
            logger.info(f"Using saved bootstrap address: {saved_addr}")
    
    if args.mode == "consumer" and (not args.bootstrap or len(args.bootstrap) == 0):
        parser.error("Consumer mode requires at least one bootstrap address (use --bootstrap or --use-saved)")
        
    # Use random port if not specified
    if args.port == 0:
        args.port = random.randint(10000, 60000)
        logger.info(f"Using random port: {args.port}")
        
    return args


if __name__ == "__main__":
    try:
        args = parse_args()
        logger.info(f"Running in {args.mode} mode on port {args.port}")
        
        if args.mode == "provider":
            trio.run(run_provider_node, args.port, args.bootstrap)
        else:
            trio.run(run_consumer_node, args.port, args.bootstrap)
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)

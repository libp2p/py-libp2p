#!/usr/bin/env python

"""
Random Walk Example for py-libp2p Kademlia DHT

This example demonstrates the Random Walk module's peer discovery capabilities
using real libp2p hosts and Kademlia DHT. It shows how the Random Walk module
automatically discovers new peers and maintains routing table health.

Usage:
    # Start bootstrap node (first node in network)
    python3 random_walk_example.py --mode bootstrap --port 9000

    # Start server nodes (they will discover peers via random walk)
    python3 random_walk_example.py --mode server --port 9001 --bootstrap /ip4/127.0.0.1/tcp/9000/p2p/<peer_id>
    python3 random_walk_example.py --mode server --port 9002 --bootstrap /ip4/127.0.0.1/tcp/9000/p2p/<peer_id>

    # Start client node (will demonstrate random walk discovery)
    python3 random_walk_example.py --mode client --bootstrap /ip4/127.0.0.1/tcp/9000/p2p/<peer_id>

    # Use default public bootstrap nodes (no --bootstrap needed for non-bootstrap modes)
    python3 random_walk_example.py --mode server --port 9001
    python3 random_walk_example.py --mode client
"""

import argparse
import asyncio
import logging
import os
import random
import secrets
import sys
import time

import base58
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.kad_dht.utils import create_key_from_binary
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.utils import info_from_p2p_addr

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("random-walk-example")

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOOTSTRAP_ADDR_LOG = os.path.join(SCRIPT_DIR, "bootstrap_nodes.txt")

# Default bootstrap nodes for testing (public libp2p bootstrap nodes)
DEFAULT_BOOTSTRAP_NODES = [
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
    "/ip4/128.199.219.111/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",
    "/ip4/104.236.76.40/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",
    "/ip4/178.62.158.247/tcp/4001/p2p/QmSoLer265NRgSp2LA3dPaeykiS1J6DifTC88f5uVQKNAd",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
]

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
    child_logger.propagate = True

# Configure random walk module logging
for module in ["random_walk", "rt_refresh_manager"]:
    child_logger = logging.getLogger(f"libp2p.routing_table.{module}")
    child_logger.setLevel(logging.INFO)
    child_logger.propagate = True


async def connect_to_bootstrap_nodes(host: IHost, bootstrap_addrs: list[str]) -> None:
    """
    Connect to the bootstrap nodes provided in the list.
    
    Args:
        host: The host instance to connect to
        bootstrap_addrs: List of bootstrap node addresses
    """
    for addr in bootstrap_addrs:
        try:
            peer_info = info_from_p2p_addr(Multiaddr(addr))
            host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)
            await host.connect(peer_info)
            logger.info(f"Connected to bootstrap node: {peer_info.peer_id}")
        except Exception as e:
            logger.error(f"Failed to connect to bootstrap node {addr}: {e}")


def save_bootstrap_addr(addr: str) -> None:
    """Append the bootstrap node's multiaddress to the log file."""
    try:
        with open(BOOTSTRAP_ADDR_LOG, "a") as f:
            f.write(addr + "\n")
        logger.info(f"Saved bootstrap address to log: {addr}")
    except Exception as e:
        logger.error(f"Failed to save bootstrap address: {e}")


def load_bootstrap_addrs() -> list[str]:
    """Load all bootstrap multiaddresses from the log file."""
    if not os.path.exists(BOOTSTRAP_ADDR_LOG):
        return []
    try:
        with open(BOOTSTRAP_ADDR_LOG) as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        logger.error(f"Failed to load bootstrap addresses: {e}")
        return []


async def demonstrate_random_walk_discovery(dht: KadDHT, interval: int = 30) -> None:
    """
    Demonstrate Random Walk peer discovery by periodically showing
    routing table statistics and triggering manual refreshes.
    
    Args:
        dht: The Kademlia DHT instance
        interval: Interval between demonstrations in seconds
    """
    logger.info("=== Random Walk Discovery Demonstration ===")
    
    iteration = 0
    while True:
        iteration += 1
        
        # Show current routing table state
        rt_size = dht.get_routing_table_size()
        connected_peers = len(dht.host.get_connected_peers())
        peerstore_size = len(dht.host.get_peerstore().peer_ids())
        
        logger.info(f"--- Iteration {iteration} ---")
        logger.info(f"Routing table size: {rt_size}")
        logger.info(f"Connected peers: {connected_peers}")
        logger.info(f"Peerstore size: {peerstore_size}")
        
        # Show some routing table peers
        if rt_size > 0:
            peer_infos = dht.routing_table.get_peer_infos()
            logger.info("Current routing table peers:")
            for i, peer_info in enumerate(peer_infos[:5]):  # Show first 5
                logger.info(f"  {i+1}. {peer_info.peer_id}")
            if len(peer_infos) > 5:
                logger.info(f"  ... and {len(peer_infos) - 5} more")
        
        # Manually trigger a random walk refresh to demonstrate the functionality
        if iteration % 2 == 0:  # Every other iteration
            logger.info("Manually triggering routing table refresh...")
            start_time = time.time()
            await dht.trigger_routing_table_refresh(force=True)
            refresh_time = time.time() - start_time
            
            new_rt_size = dht.get_routing_table_size()
            peers_discovered = new_rt_size - rt_size
            logger.info(f"Refresh completed in {refresh_time:.2f}s")
            logger.info(f"Net peers discovered: {peers_discovered} (new size: {new_rt_size})")
        
        logger.info(f"Next demonstration in {interval} seconds...")
        await trio.sleep(interval)


async def store_and_retrieve_values(dht: KadDHT, node_id: str) -> None:
    """
    Store and retrieve some values to demonstrate DHT functionality
    alongside random walk discovery.
    
    Args:
        dht: The Kademlia DHT instance
        node_id: Identifier for this node
    """
    # Store a value
    key = create_key_from_binary(f"random-walk-test-{node_id}".encode())
    value = f"Hello from Random Walk node {node_id} at {time.time()}".encode()
    
    try:
        await dht.put_value(key, value)
        logger.info(f"Stored value: {value.decode()}")
        logger.info(f"Key: {base58.b58encode(key).decode()}")
    except Exception as e:
        logger.error(f"Failed to store value: {e}")
    
    # Try to retrieve values from other nodes
    await trio.sleep(5)  # Give time for propagation
    
    for test_id in ["1", "2", "3"]:
        if test_id != node_id:
            try:
                test_key = create_key_from_binary(f"random-walk-test-{test_id}".encode())
                retrieved_value = await dht.get_value(test_key)
                if retrieved_value:
                    logger.info(f"Retrieved value from node {test_id}: {retrieved_value.decode()}")
                else:
                    logger.debug(f"No value found for node {test_id}")
            except Exception as e:
                logger.debug(f"Failed to retrieve value for node {test_id}: {e}")


async def run_node(
    port: int, 
    mode: str, 
    bootstrap_addrs: list[str] | None = None,
    demo_interval: int = 30
) -> None:
    """
    Run a node that demonstrates Random Walk peer discovery.
    
    Args:
        port: Port to listen on
        mode: Node mode (bootstrap, server, client)
        bootstrap_addrs: List of bootstrap node addresses
        demo_interval: Interval between discovery demonstrations
    """
    try:
        if port <= 0:
            port = random.randint(10000, 60000)
        
        logger.info(f"Starting {mode} node on port {port}")
        
        # Determine DHT mode
        if mode == "bootstrap":
            dht_mode = DHTMode.SERVER
        elif mode == "server":
            dht_mode = DHTMode.SERVER  
        elif mode == "client":
            dht_mode = DHTMode.CLIENT
        else:
            logger.error(f"Invalid mode: {mode}. Must be 'bootstrap', 'server', or 'client'")
            sys.exit(1)
        
        # Load existing bootstrap addresses for non-bootstrap nodes
        existing_bootstrap_addrs = []
        if mode != "bootstrap":
            existing_bootstrap_addrs = load_bootstrap_addrs()
            if existing_bootstrap_addrs:
                logger.info(f"Loaded {len(existing_bootstrap_addrs)} bootstrap addresses from log")
        
        # Combine provided and existing bootstrap addresses
        all_bootstrap_addrs = []
        if bootstrap_addrs:
            all_bootstrap_addrs.extend(bootstrap_addrs)
        all_bootstrap_addrs.extend(existing_bootstrap_addrs)
        
        # If no bootstrap addresses provided or found, use default public bootstrap nodes
        if not all_bootstrap_addrs and mode != "bootstrap":
            all_bootstrap_addrs = DEFAULT_BOOTSTRAP_NODES[:3]  # Use first 3 for testing
            logger.info(f"Using default bootstrap nodes: {len(all_bootstrap_addrs)} nodes")
        
        if not all_bootstrap_addrs and mode != "bootstrap":
            logger.warning("No bootstrap addresses available. This node may not discover peers.")
        
        # Create host
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)
        listen_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")
        
        async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
            # Start the peer-store cleanup task
            nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
            
            peer_id = host.get_id().pretty()
            addr_str = f"/ip4/127.0.0.1/tcp/{port}/p2p/{peer_id}"
            
            logger.info(f"Node address: {addr_str}")
            logger.info(f"Node peer ID: {peer_id}")
            
            # Connect to bootstrap nodes
            if all_bootstrap_addrs:
                await connect_to_bootstrap_nodes(host, all_bootstrap_addrs)
                logger.info(f"Connected to {len(host.get_connected_peers())} bootstrap peers")
            
            # Create DHT with Random Walk enabled
            dht = KadDHT(host, dht_mode)
            
            # Add connected peers to routing table
            for connected_peer_id in host.get_connected_peers():
                await dht.routing_table.add_peer(connected_peer_id)
            
            logger.info(f"Initial routing table size: {dht.get_routing_table_size()}")
            
            # Save bootstrap address if this is a bootstrap node
            if mode == "bootstrap":
                save_bootstrap_addr(addr_str)
                logger.info("Bootstrap node started. Other nodes can connect using:")
                logger.info(f"  --bootstrap {addr_str}")
            
            # Start the DHT service (this also starts the Random Walk module)
            async with background_trio_service(dht):
                logger.info(f"DHT service started in {dht_mode.value} mode")
                logger.info("Random Walk module is automatically enabled")
                
                # Generate a unique node identifier for demonstrations
                node_id = str(random.randint(1, 1000))
                
                # Start concurrent tasks
                async with trio.open_nursery() as task_nursery:
                    # Start random walk discovery demonstration
                    task_nursery.start_soon(demonstrate_random_walk_discovery, dht, demo_interval)
                    
                    # Store and retrieve values if this is a server
                    if dht_mode == DHTMode.SERVER:
                        task_nursery.start_soon(store_and_retrieve_values, dht, node_id)
                    
                    # Keep the node running and show periodic status
                    async def status_reporter():
                        while True:
                            await trio.sleep(60)  # Report every minute
                            logger.debug(
                                "Status - Connected: %d, Routing table: %d, Peerstore: %d",
                                len(dht.host.get_connected_peers()),
                                dht.get_routing_table_size(),
                                len(dht.host.get_peerstore().peer_ids()),
                            )
                    
                    task_nursery.start_soon(status_reporter)
                    
                    # Keep running
                    await trio.sleep_forever()
    
    except Exception as e:
        logger.error(f"Node error: {e}", exc_info=True)
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Random Walk Example for py-libp2p Kademlia DHT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start bootstrap node
  python3 random_walk_example.py --mode bootstrap --port 9000
  
  # Start server nodes
  python3 random_walk_example.py --mode server --port 9001 --bootstrap /ip4/127.0.0.1/tcp/9000/p2p/<peer_id>
  python3 random_walk_example.py --mode server --port 9002 --bootstrap /ip4/127.0.0.1/tcp/9000/p2p/<peer_id>
  
  # Start client node
  python3 random_walk_example.py --mode client --bootstrap /ip4/127.0.0.1/tcp/9000/p2p/<peer_id>
  
  # Use default public bootstrap nodes (simpler testing)
  python3 random_walk_example.py --mode server --port 9001
  python3 random_walk_example.py --mode client
        """
    )
    
    parser.add_argument(
        "--mode",
        choices=["bootstrap", "server", "client"],
        default="server",
        help="Node mode: bootstrap (first node), server (DHT server), or client (DHT client)"
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
        help="Multiaddrs of bootstrap nodes (space-separated). If not provided for non-bootstrap modes, default public bootstrap nodes will be used."
    )
    
    parser.add_argument(
        "--demo-interval",
        type=int,
        default=30,
        help="Interval between random walk demonstrations in seconds"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        # Also enable debug logging for random walk modules
        logging.getLogger("libp2p.routing_table.random_walk").setLevel(logging.DEBUG)
        logging.getLogger("libp2p.routing_table.rt_refresh_manager").setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)
    
    return args


def main():
    """Main entry point for the random walk example."""
    try:
        args = parse_args()
        
        logger.info("=== Random Walk Example for py-libp2p ===")
        logger.info(f"Mode: {args.mode}")
        logger.info(f"Port: {args.port}")
        logger.info(f"Demo interval: {args.demo_interval}s")
        
        if args.bootstrap:
            logger.info(f"Bootstrap nodes: {args.bootstrap}")
        
        trio.run(run_node, args.port, args.mode, args.bootstrap, args.demo_interval)
        
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.critical(f"Example failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

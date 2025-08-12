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
from libp2p.abc import IHost, IPeerStore
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

# Default bootstrap nodes for testing (only TCP-compatible ones)
DEFAULT_BOOTSTRAP_NODES = [
    # Official IPFS bootstrap nodes (TCP only)
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",  # mars.i.ipfs.io
    
    # DNS-based bootstrap nodes (these resolve to multiple addresses)
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",  # rust-libp2p-server
    # "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
    
    # Additional stable IPFS nodes (TCP compatible)
    # "/ip4/128.199.219.111/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",  # ipfs.io
    # "/ip4/104.236.76.40/tcp/4001/p2p/QmSoLV4Bbm51jM9C4gDYZQ9Cy3U6aXMJDAbzgu2fzaDs64",   # ipfs.io
    # "/ip4/178.62.158.247/tcp/4001/p2p/QmSoLer265NRgSp2LA3dPaeykiS1J6DifTC88f5uVQKNAd", # ipfs.io
    
    # # Community and research nodes
    # "/ip4/94.130.135.167/tcp/4001/p2p/QmfMfgCkJp3dnX8F4YGBWKJqkqWfQFZKWbCFRJ4gLxKwxB",   # community node
    # "/ip4/147.75.77.187/tcp/4001/p2p/QmdnXwLrC8p1ueiq2Qya8joNvk3TVVDAut7PrikmZwubtR",   # packet.net node
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

# Configure random walk module logging with proper handlers
def setup_random_walk_logging():
    """Setup proper logging for random walk modules."""
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    
    # Configure main random walk logger
    rw_logger = logging.getLogger("libp2p.discovery.random_walk")
    rw_logger.setLevel(logging.INFO)
    rw_logger.handlers.clear()  # Clear any existing handlers
    rw_logger.addHandler(handler)
    rw_logger.propagate = False
    
    # Configure RT refresh manager logger  
    rt_logger = logging.getLogger("libp2p.discovery.random_walk.rt_refresh_manager")
    rt_logger.setLevel(logging.INFO)
    rt_logger.handlers.clear()
    rt_logger.addHandler(handler)
    rt_logger.propagate = False
    
    # Configure specific random walk module logger
    rw_module_logger = logging.getLogger("libp2p.discovery.random_walk.random_walk")
    rw_module_logger.setLevel(logging.INFO)
    rw_module_logger.handlers.clear()
    rw_module_logger.addHandler(handler)
    rw_module_logger.propagate = False
    
    logger.info("Random walk logging configured with dedicated handlers")

# Setup random walk logging
setup_random_walk_logging()

# Configure libp2p discovery random_walk parent logger (backup)
random_walk_parent_logger = logging.getLogger("libp2p.discovery.random_walk")
if not random_walk_parent_logger.handlers:
    random_walk_parent_logger.setLevel(logging.INFO)
    random_walk_parent_logger.propagate = True

# Also configure the kad_dht module for better visibility
kad_dht_logger = logging.getLogger("libp2p.kad_dht")
kad_dht_logger.setLevel(logging.INFO)
kad_dht_logger.propagate = True

# Suppress noisy multiaddr logs
multiaddr_logger = logging.getLogger("multiaddr.transforms")
multiaddr_logger.setLevel(logging.WARNING)
multiaddr_codecs_logger = logging.getLogger("multiaddr.codecs")
multiaddr_codecs_logger.setLevel(logging.WARNING)


def filter_compatible_peer_info(peer_info) -> bool:
    """
    Filter peer info to check if it has compatible addresses (TCP + IPv4).
    
    Args:
        peer_info: PeerInfo object
    
    Returns:
        bool: True if peer has compatible addresses
    """
    if not hasattr(peer_info, 'addrs') or not peer_info.addrs:
        return False
    
    for addr in peer_info.addrs:
        addr_str = str(addr)
        # Check for TCP and IPv4 compatibility
        if '/tcp/' in addr_str and '/ip4/' in addr_str and '/quic' not in addr_str:
            return True
    
    return False


async def configure_dht_logging(dht: KadDHT) -> None:
    """
    Configure logging for DHT and Random Walk components after DHT initialization.
    
    Args:
        dht: The Kademlia DHT instance
    """
    # Ensure RT Refresh Manager logging is properly configured
    rt_refresh_logger = logging.getLogger("libp2p.discovery.random_walk.rt_refresh_manager")
    rt_refresh_logger.setLevel(logging.INFO)
    rt_refresh_logger.propagate = True
    
    # Also configure the random walk logger
    random_walk_logger = logging.getLogger("libp2p.discovery.random_walk.random_walk")
    random_walk_logger.setLevel(logging.INFO)
    random_walk_logger.propagate = True
    
    logger.info("DHT and Random Walk logging configured")
    logger.info(f"RT Refresh Manager logger level: {rt_refresh_logger.level}")
    logger.info(f"Random Walk logger level: {random_walk_logger.level}")

async def maintain_connections(host: IHost) -> None:
    """
    Periodically maintain connections to ensure the host remains connected
    to a healthy set of peers.
    
    Args:
        host: The host instance to connect to
        peerstore: The peerstore instance to manage peer connections
    """
    while True:
        try:
            # Get current connected peers
            connected_peers = host.get_connected_peers()
            logger.info(f"Currently connected peers: {len(connected_peers)}")
            list_peers = host.get_peerstore().peers_with_addrs()
            logger.info(f"Peers in peerstore: {len(list_peers)}")
            # If too few connections, try to connect to bootstrap nodes
            if len(connected_peers) < 20:
                logger.info("Not enough connected peers, reconnecting to nodes...")
                # Attempt to reconnect to random peers in list_peers
                # Filter peers to only those with compatible addresses
                compatible_peers = []
                for peer_id in list_peers:
                    try:
                        peer_info = host.get_peerstore().peer_info(peer_id)
                        if filter_compatible_peer_info(peer_info):
                            compatible_peers.append(peer_id)
                    except Exception as e:
                        logger.debug(f"Error checking peer {peer_id}: {e}")
                
                logger.info(f"Found {len(compatible_peers)} compatible peers out of {len(list_peers)}")
                
                if compatible_peers:
                    random_peers = random.sample(compatible_peers, min(50, len(compatible_peers)))
                    for peer_id in random_peers:
                        if peer_id in connected_peers:
                            logger.debug(f"Already connected to {peer_id}, skipping")
                            continue
                        try:
                            # add a timeout to avoid blocking
                            with trio.move_on_after(5) as cancel_scope:
                                logger.debug(f"Connecting to random peer: {peer_id}")
                                peer_info = host.get_peerstore().peer_info(peer_id)
                                await host.connect(peer_info)
                                logger.info(f"Connected to peer: {peer_id}")
                            
                            if cancel_scope.cancelled_caught:
                                logger.warning(f"Connection to {peer_id} timed out")
                        except Exception as e:
                            logger.error(f"Failed to connect to peer {peer_id}: {e}")
                else:
                    logger.warning("No compatible peers found to connect to")
            else:
                logger.debug("Sufficient connected peers, no action needed")
            # Sleep before next check
            await trio.sleep(15)  # Check every 15 seconds
        except Exception as e:
            logger.error(f"Error maintaining connections: {e}")


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
        logger.info(f"--- Iteration {iteration} ---")
        logger.info(f"Routing table size: {dht.get_routing_table_size()}")
        logger.info(f"Connected peers: {len(dht.host.get_connected_peers())}")
        logger.info(f"Peerstore size: {len(dht.host.get_peerstore().peer_ids())}")
        
        # Manually trigger a random walk refresh to demonstrate the functionality
        if iteration % 2 == 0:  # Every other iteration
            logger.info("Manually triggering routing table refresh (this will start random walks)...")
            start_time = time.time()
            # await dht.trigger_routing_table_refresh(force=True)
            # await dht.find_peer(dht.host.get_id())
            refresh_time = time.time() - start_time
            
            new_rt_size = dht.get_routing_table_size()
            peers_discovered = new_rt_size - dht.get_routing_table_size()
            logger.info(f"Refresh completed in {refresh_time:.2f}s")
            logger.info(f"Net peers discovered: {peers_discovered} (new size: {new_rt_size})")
        else:
            logger.info("Random walk module is running automatically in the background...")
        
        logger.info(f"Next demonstration in {interval} seconds...")
        await trio.sleep(interval)

async def run_node(
    port: int, 
    mode: str, 
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
        if mode == "server":
            dht_mode = DHTMode.SERVER
        elif mode == "client":
            dht_mode = DHTMode.CLIENT
        else:
            logger.error(f"Invalid mode: {mode}. Must be 'server' or 'client'")
            sys.exit(1)
        
        # Create host
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair, bootstrap=DEFAULT_BOOTSTRAP_NODES)
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
        
        async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
            # Start the peer-store cleanup task
            nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
            nursery.start_soon(maintain_connections, host)
            
            peer_id = host.get_id().pretty()
            addr_str = f"/ip4/0.0.0.0/tcp/{port}/p2p/{peer_id}"

            logger.info(f"Node address: {addr_str}")
            logger.info(f"Node peer ID: {peer_id}")

            # Create DHT with Random Walk enabled
            dht = KadDHT(host, dht_mode)
            
            # Configure DHT logging after creation
            await configure_dht_logging(dht)
            
            # # Add connected peers to routing table
            for connected_peer_id in host.get_connected_peers():
                await dht.routing_table.add_peer(connected_peer_id)
            
            logger.info(f"Initial routing table size: {dht.get_routing_table_size()}")
            
            # Start the DHT service (this also starts the Random Walk module)
            async with background_trio_service(dht):
                logger.info(f"DHT service started in {dht_mode.value} mode")
                logger.info("Random Walk module is automatically enabled")
                logger.info("RT Refresh Manager should now be running and performing random walks")
                
                # Start concurrent tasks
                async with trio.open_nursery() as task_nursery:
                    # Start random walk discovery demonstration
                    task_nursery.start_soon(demonstrate_random_walk_discovery, dht, demo_interval)
                    
                    # Keep the node running and show periodic status
                    async def status_reporter():
                        while True:
                            await trio.sleep(30)  # Report every 30 seconds
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
        choices=["server", "client"],
        default="server",
        help="Node mode: server (DHT server), or client (DHT client)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 for random)"
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
        logging.getLogger("libp2p.discovery.random_walk.random_walk").setLevel(logging.DEBUG)
        logging.getLogger("libp2p.discovery.random_walk.rt_refresh_manager").setLevel(logging.DEBUG)
        logging.getLogger("libp2p.discovery.random_walk").setLevel(logging.DEBUG)
        logging.getLogger("libp2p.kad_dht").setLevel(logging.DEBUG)
        logger.info("Verbose logging enabled - you'll see detailed random walk logs")
    else:
        logging.getLogger().setLevel(logging.INFO)
        # Ensure INFO level for rt_refresh_manager even in non-verbose mode
        logging.getLogger("libp2p.discovery.random_walk.rt_refresh_manager").setLevel(logging.INFO)
        logging.getLogger("libp2p.discovery.random_walk.random_walk").setLevel(logging.INFO)
        logger.info("Standard logging enabled - you'll see random walk start messages")
    
    return args


def main():
    """Main entry point for the random walk example."""
    try:
        args = parse_args()
        
        logger.info("=== Random Walk Example for py-libp2p ===")
        logger.info(f"Mode: {args.mode}")
        logger.info(f"Port: {args.port}")
        logger.info(f"Demo interval: {args.demo_interval}s")

        trio.run(run_node, args.port, args.mode, args.demo_interval)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.critical(f"Example failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

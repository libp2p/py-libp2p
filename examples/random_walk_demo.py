#!/usr/bin/env python3
"""
Example demonstrating the Random Walk module integration with Kademlia DHT.

This example shows how to:
1. Create a Kademlia DHT with Random Walk enabled
2. Trigger manual refreshes
3. Monitor routing table population
"""

import asyncio
import logging
import trio
from contextlib import asynccontextmanager
from typing import List

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.routing_table.random_walk import RandomWalk
from libp2p.routing_table.rt_refresh_manager import RTRefreshManager
from libp2p.routing_table.config import RANDOM_WALK_ENABLED


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class MockRoutingTable:
    """Mock routing table for demonstration."""
    
    def __init__(self):
        self.peers = {}
        self._size = 0
    
    def size(self) -> int:
        return self._size
    
    def get_peer_infos(self) -> List[PeerInfo]:
        return list(self.peers.values())
    
    def add_peer(self, peer_info: PeerInfo) -> bool:
        if peer_info.peer_id not in self.peers:
            self.peers[peer_info.peer_id] = peer_info
            self._size += 1
            logger.info(f"Added peer {peer_info.peer_id} to routing table")
            return True
        return False
    
    def remove_peer(self, peer_id: ID) -> None:
        if peer_id in self.peers:
            del self.peers[peer_id]
            self._size -= 1
            logger.info(f"Removed peer {peer_id} from routing table")


class MockHost:
    """Mock host for demonstration."""
    
    def __init__(self, peer_id: ID):
        self.peer_id = peer_id
    
    async def connect(self, peer_info: PeerInfo):
        """Mock connect - simulate some connections failing."""
        # Simulate 70% success rate
        import random
        if random.random() < 0.7:
            logger.debug(f"Successfully connected to {peer_info.peer_id}")
        else:
            logger.debug(f"Failed to connect to {peer_info.peer_id}")
            raise Exception("Connection failed")


def mock_query_function(target_key: str):
    """Mock query function that returns some simulated peers."""
    
    @asynccontextmanager
    async def query_context():
        # Simulate query delay
        await trio.sleep(0.1)
        
        # Generate some mock peers
        mock_peers = []
        for i in range(3):  # Return 3 peers per query
            peer_id = ID(f"mock_peer_{target_key[:8]}_{i}".encode())
            peer_info = PeerInfo(peer_id, [])  # Empty addrs for demo
            mock_peers.append(peer_info)
        
        logger.debug(f"Query for {target_key[:8]}... returned {len(mock_peers)} peers")
        yield mock_peers
    
    return query_context()


def mock_ping_function(peer_id: ID):
    """Mock ping function."""
    
    @asynccontextmanager
    async def ping_context():
        # Simulate ping delay
        await trio.sleep(0.05)
        
        # Simulate 80% success rate
        import random
        result = random.random() < 0.8
        logger.debug(f"Ping {peer_id}: {'success' if result else 'failed'}")
        yield result
    
    return ping_context()


def mock_validation_function(peer_info: PeerInfo):
    """Mock validation function."""
    
    @asynccontextmanager
    async def validation_context():
        # Simulate validation delay
        await trio.sleep(0.02)
        
        # Simulate 60% validation success rate
        import random
        result = random.random() < 0.6
        logger.debug(f"Validation {peer_info.peer_id}: {'passed' if result else 'failed'}")
        yield result
    
    return validation_context()


async def demonstrate_random_walk():
    """Demonstrate the Random Walk functionality."""
    
    logger.info("=== Random Walk Module Demonstration ===")
    
    # Create mock components
    local_peer_id = ID(b"local_peer_demo")
    mock_host = MockHost(local_peer_id)
    mock_routing_table = MockRoutingTable()
    
    logger.info(f"Created DHT node with peer ID: {local_peer_id}")
    logger.info(f"Initial routing table size: {mock_routing_table.size()}")
    
    # Create RT Refresh Manager
    rt_refresh_manager = RTRefreshManager(
        host=mock_host,
        routing_table=mock_routing_table,
        local_peer_id=local_peer_id,
        query_function=mock_query_function,
        ping_function=mock_ping_function,
        validation_function=mock_validation_function,
        enable_auto_refresh=False,  # Disable auto for demo
        min_refresh_threshold=1,  # Low threshold for demo
    )
    
    logger.info("Created RT Refresh Manager")
    
    try:
        # Start the refresh manager
        async with trio.open_nursery() as nursery:
            nursery.start_soon(rt_refresh_manager.start)
            
            # Wait a bit for startup
            await trio.sleep(0.5)
            
            # Demonstrate manual refresh
            logger.info("Triggering manual routing table refresh...")
            await rt_refresh_manager.trigger_refresh(force=True)
            
            # Wait for refresh to complete
            await trio.sleep(2.0)
            
            logger.info(f"Routing table size after refresh: {mock_routing_table.size()}")
            
            # Show peers in routing table
            peers = mock_routing_table.get_peer_infos()
            for i, peer in enumerate(peers):
                logger.info(f"Peer {i+1}: {peer.peer_id}")
            
            # Demonstrate another refresh
            logger.info("Triggering second refresh...")
            await rt_refresh_manager.trigger_refresh(force=True)
            await trio.sleep(2.0)
            
            logger.info(f"Final routing table size: {mock_routing_table.size()}")
            
            # Stop the refresh manager
            await rt_refresh_manager.stop()
            
    except Exception as e:
        logger.error(f"Error during demonstration: {e}")
        raise
    
    logger.info("=== Demonstration completed successfully ===")


async def demonstrate_random_walk_standalone():
    """Demonstrate standalone Random Walk functionality."""
    
    logger.info("=== Standalone Random Walk Demonstration ===")
    
    # Create mock components
    local_peer_id = ID(b"standalone_demo")
    mock_host = MockHost(local_peer_id)
    
    # Create random walk instance
    random_walk = RandomWalk(
        host=mock_host,
        local_peer_id=local_peer_id,
        query_function=mock_query_function,
        validation_function=mock_validation_function,
        ping_function=mock_ping_function,
    )
    
    logger.info("Created standalone Random Walk instance")
    
    # Test random peer ID generation
    logger.info("Testing random peer ID generation:")
    for i in range(3):
        random_id = random_walk.generate_random_peer_id()
        logger.info(f"Random ID {i+1}: {random_id}")
    
    # Perform a single random walk
    logger.info("Performing single random walk...")
    peers = await random_walk.perform_random_walk()
    logger.info(f"Single walk discovered {len(peers)} validated peers")
    
    # Perform concurrent random walks
    logger.info("Performing concurrent random walks...")
    peers = await random_walk.run_concurrent_random_walks(count=2)
    logger.info(f"Concurrent walks discovered {len(peers)} unique validated peers")
    
    for i, peer in enumerate(peers):
        logger.info(f"Validated peer {i+1}: {peer.peer_id}")
    
    logger.info("=== Standalone demonstration completed ===")


async def main():
    """Main function."""
    try:
        await demonstrate_random_walk_standalone()
        await trio.sleep(1.0)
        await demonstrate_random_walk()
    except Exception as e:
        logger.error(f"Demonstration failed: {e}")
        raise


if __name__ == "__main__":
    trio.run(main)

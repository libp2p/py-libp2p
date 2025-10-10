#!/usr/bin/env python

"""
Test script for DHT Messaging Implementation

This script tests the basic functionality of the DHT messaging system
to ensure it works correctly.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add the parent directory to the path to import our modules
sys.path.insert(0, str(Path(__file__).parent))

from dht_messaging import DHTMessagingNode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("test-dht-messaging")


async def test_dht_messaging():
    """Test the DHT messaging functionality."""
    logger.info("🧪 Testing DHT Messaging Implementation")
    
    try:
        # Create a test node
        node = DHTMessagingNode(port=0, username="TestUser")
        
        # Start the node in a background task
        async with asyncio.TaskGroup() as tg:
            # Start the node
            node_task = tg.create_task(node.start())
            
            # Wait a bit for the node to initialize
            await asyncio.sleep(5)
            
            # Check if the node is running
            if node.host and node.dht and node.pubsub:
                logger.info("✅ Node initialized successfully")
                logger.info(f"📍 Peer ID: {node.host.get_id()}")
                logger.info(f"🌐 Listening addresses: {node.host.get_addrs()}")
                
                # Check DHT status
                routing_peers = len(node.dht.routing_table.peers)
                logger.info(f"🔍 DHT routing table has {routing_peers} peers")
                
                # Check PubSub status
                if node.pubsub:
                    logger.info("📢 PubSub service is running")
                
                logger.info("✅ All components initialized successfully")
            else:
                logger.error("❌ Node failed to initialize properly")
                return False
            
            # Stop the node after testing
            node.stop()
            
        logger.info("🎉 Test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        return False


async def main():
    """Main test function."""
    logger.info("🚀 Starting DHT Messaging Tests")
    logger.info("=" * 50)
    
    success = await test_dht_messaging()
    
    if success:
        logger.info("✅ All tests passed!")
        return 0
    else:
        logger.error("❌ Tests failed!")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("🛑 Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Test error: {e}")
        sys.exit(1)

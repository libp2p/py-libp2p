#!/usr/bin/env python3
"""Simplified Python hole punching client for interop tests."""

import argparse
import json
import logging
import time

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.id import ID

logger = logging.getLogger(__name__)

class SimpleHolePunchClient:
    def __init__(self):
        self.host = None
        self.target_peer_id = None
        self.connected_via_relay = False
        
    async def start(self, relay_addr, target_peer_id, duration=60):
        """Start the simple hole punch client."""
        # Create py-libp2p host (new_host is synchronous, not async)
        self.host = new_host()  # REMOVE await
        self.target_peer_id = ID.from_base58(target_peer_id)
        
        logger.info(f"Python hole punch client running on: {self.host.get_addrs()}")
        logger.info(f"Python hole punch client peer ID: {self.host.get_id()}")
        
        await self._attempt_connection(relay_addr, target_peer_id)
        
        # Wait for specified duration
        logger.info(f"Monitoring (relayed) connections for {duration} seconds...")
        await trio.sleep(duration)
        
        logger.info("Simple hole punch client shutting down...")
        
    async def _attempt_connection(self, relay_addr, target_peer_id):
        """Attempt connection with the target peer through relay."""
        try:
            target_id = ID.from_base58(target_peer_id)
            
            # Create circuit relay address for target
            circuit_addr = Multiaddr(f"{relay_addr}/p2p-circuit/p2p/{target_peer_id}")
            
            logger.info(f"Attempting to connect to target {target_id} through relay...")
            
            # Connect to target through relay
            target_peer_info = PeerInfo(target_id, [circuit_addr])
            await self.host.connect(target_peer_info)
            
            self.connected_via_relay = True
            logger.info("SUCCESS: Connected to target through relay!")
            
            # Try to open a test stream
            await self._test_stream_connection(target_id)
            
        except Exception as e:
            logger.error(f"Error during connection attempt: {e}")
    
    async def _test_stream_connection(self, target_id):
        """Test stream connection to the target peer."""
        try:
            logger.info("Opening test stream to target...")
            stream = await self.host.new_stream(target_id, ["/test/ping/1.0.0"])
            
            if stream:
                logger.info("SUCCESS: Opened test stream to target")
                
                # Send a simple message
                test_message = b"Hello from Python client!"
                await stream.write(test_message)
                
                # Try to read response
                try:
                    response_data = await stream.read(1024)
                    if response_data:
                        logger.info(f"Received response: {response_data.decode('utf-8', errors='ignore')}")
                    else:
                        logger.warning("No response data received")
                except Exception as e:
                    logger.warning(f"Error reading stream response: {e}")
                
                await stream.close()
            else:
                logger.warning("Failed to open test stream")
                
        except Exception as e:
            logger.error(f"Error testing stream connection: {e}")
    
    def get_info(self):
        """Get client information."""
        if not self.host:
            return None
            
        return {
            "peer_id": str(self.host.get_id()),
            "addresses": [str(addr) for addr in self.host.get_addrs()],
            "target_peer": str(self.target_peer_id) if self.target_peer_id else None,
            "connection_count": len(self.host.get_network().connections),
            "connected_via_relay": self.connected_via_relay
        }

async def main():
    """Main function for the simple hole punching client."""
    parser = argparse.ArgumentParser(description="Simple Python Hole Punch Client")
    parser.add_argument("--relay", required=True, help="Relay multiaddr")
    parser.add_argument("--target", required=True, help="Target peer ID")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--print-id-only", action="store_true", help="Print only peer ID and exit")
    parser.add_argument("--print-info", action="store_true", help="Print client info as JSON and exit")
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    client = SimpleHolePunchClient()
    
    if args.print_id_only or args.print_info:
        # Start client briefly to get info
        try:
            client.host = new_host()  # REMOVE await
            if args.target:
                client.target_peer_id = ID.from_base58(args.target)
            
            if args.print_id_only:
                print(str(client.host.get_id()), end='')
                return
                
            if args.print_info:
                info = client.get_info()
                print(json.dumps(info), end='')
                return
                
        except Exception as e:
            logger.error(f"Error getting client info: {e}")
            return
    else:
        try:
            await client.start(args.relay, args.target, args.duration)
        except Exception as e:
            logger.error(f"Error running simple hole punch client: {e}")

if __name__ == "__main__":
    trio.run(main)

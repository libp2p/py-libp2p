#!/usr/bin/env python

"""
Decentralized Messaging with DHT Bootstrap - ETH Delhi Hackathon

This example demonstrates a truly decentralized messaging system that uses
Kademlia DHT for peer discovery and routing, eliminating the need for
hardcoded bootstrap servers. Peers can find each other by peer ID through
DHT lookups and establish direct connections for messaging.

Key Features:
- DHT-based peer discovery (no bootstrap servers)
- PubSub messaging over discovered peers
- Automatic peer routing through DHT
- Serverless architecture
"""

import argparse
import asyncio
import logging
import random
import secrets
import sys
import time
from typing import Optional

import base58
import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.async_service import background_trio_service
from libp2p.utils.address_validation import find_free_port, get_available_interfaces

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("dht-messaging")

# Protocol IDs
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
MESSAGING_TOPIC = "dht-messaging"

# Global variables for peer discovery
discovered_peers = set()
peer_discovery_event = trio.Event()


class DHTMessagingNode:
    """
    A decentralized messaging node that uses DHT for peer discovery
    and PubSub for messaging.
    """

    def __init__(self, port: int, username: str = None):
        self.port = port
        self.username = username or f"user_{secrets.token_hex(4)}"
        self.host: Optional[IHost] = None
        self.dht: Optional[KadDHT] = None
        self.pubsub: Optional[Pubsub] = None
        self.gossipsub: Optional[GossipSub] = None
        self.termination_event = trio.Event()
        self.connected_peers = set()

    async def start(self) -> None:
        """Start the DHT messaging node."""
        try:
            # Create host with random key pair
            key_pair = create_new_key_pair(secrets.token_bytes(32))
            self.host = new_host(
                key_pair=key_pair,
                muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
            )

            # Get available interfaces
            listen_addrs = get_available_interfaces(self.port)

            async with self.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
                # Start peer store cleanup
                nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)

                logger.info(f"🚀 Starting DHT Messaging Node: {self.username}")
                logger.info(f"📍 Peer ID: {self.host.get_id()}")
                logger.info(f"🌐 Listening on: {listen_addrs}")

                # Initialize DHT in SERVER mode for peer discovery
                self.dht = KadDHT(self.host, DHTMode.SERVER, enable_random_walk=True)
                
                # Initialize GossipSub and PubSub
                self.gossipsub = GossipSub(
                    protocols=[GOSSIPSUB_PROTOCOL_ID],
                    degree=4,  # Maintain 4 peers in mesh
                    degree_low=2,  # Lower bound
                    degree_high=6,  # Upper bound
                    time_to_live=60,
                    gossip_window=3,
                    gossip_history=5,
                    heartbeat_initial_delay=1.0,
                    heartbeat_interval=10,
                )
                self.pubsub = Pubsub(self.host, self.gossipsub)

                # Start services
                async with background_trio_service(self.dht):
                    async with background_trio_service(self.pubsub):
                        async with background_trio_service(self.gossipsub):
                            await self.pubsub.wait_until_ready()
                            logger.info("✅ All services started successfully")

                            # Start background tasks
                            nursery.start_soon(self._peer_discovery_loop)
                            nursery.start_soon(self._peer_connection_loop)
                            nursery.start_soon(self._messaging_loop)
                            nursery.start_soon(self._status_monitor)

                            # Wait for termination
                            await self.termination_event.wait()

        except Exception as e:
            logger.error(f"❌ Error starting node: {e}")
            raise

    async def _peer_discovery_loop(self) -> None:
        """Continuously discover peers through DHT."""
        logger.info("🔍 Starting peer discovery loop...")
        
        while not self.termination_event.is_set():
            try:
                # Get connected peers from DHT routing table
                routing_peers = list(self.dht.routing_table.peers.keys())
                
                # Get connected peers from host
                connected_peers = set(self.host.get_connected_peers())
                
                # Find new peers to connect to
                new_peers = set(routing_peers) - connected_peers - {self.host.get_id()}
                
                if new_peers:
                    logger.info(f"🔍 Discovered {len(new_peers)} new peers via DHT")
                    for peer_id in new_peers:
                        if peer_id not in discovered_peers:
                            discovered_peers.add(peer_id)
                            logger.info(f"➕ New peer discovered: {peer_id.pretty()}")
                
                # Signal that we have discovered peers
                if discovered_peers and not peer_discovery_event.is_set():
                    peer_discovery_event.set()
                
                await trio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"❌ Error in peer discovery: {e}")
                await trio.sleep(5)

    async def _peer_connection_loop(self) -> None:
        """Continuously attempt to connect to discovered peers."""
        logger.info("🔗 Starting peer connection loop...")
        
        while not self.termination_event.is_set():
            try:
                # Wait for peer discovery
                await peer_discovery_event.wait()
                
                # Try to connect to discovered peers
                for peer_id in list(discovered_peers):
                    if peer_id not in self.connected_peers and peer_id != self.host.get_id():
                        try:
                            # Get peer info from DHT
                            peer_info = await self.dht.peer_routing.find_peer(peer_id)
                            if peer_info:
                                logger.info(f"🔗 Attempting to connect to {peer_id.pretty()}")
                                await self.host.connect(peer_info)
                                self.connected_peers.add(peer_id)
                                logger.info(f"✅ Connected to {peer_id.pretty()}")
                            else:
                                logger.debug(f"⚠️  No peer info found for {peer_id.pretty()}")
                        except Exception as e:
                            logger.debug(f"❌ Failed to connect to {peer_id.pretty()}: {e}")
                
                await trio.sleep(10)  # Try connections every 10 seconds
                
            except Exception as e:
                logger.error(f"❌ Error in peer connection: {e}")
                await trio.sleep(10)

    async def _messaging_loop(self) -> None:
        """Handle messaging functionality."""
        logger.info("💬 Starting messaging loop...")
        
        # Subscribe to messaging topic
        subscription = await self.pubsub.subscribe(MESSAGING_TOPIC)
        logger.info(f"📢 Subscribed to topic: {MESSAGING_TOPIC}")
        
        # Start message receiving task
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._receive_messages, subscription)
            nursery.start_soon(self._send_messages)

    async def _receive_messages(self, subscription) -> None:
        """Receive and display messages from other peers."""
        while not self.termination_event.is_set():
            try:
                message = await subscription.get()
                sender_id = base58.b58encode(message.from_id).decode()[:8]
                message_text = message.data.decode('utf-8')
                
                # Don't display our own messages
                if message.from_id != self.host.get_id().to_bytes():
                    print(f"\n💬 [{sender_id}]: {message_text}")
                    print(f"{self.username}> ", end="", flush=True)
                    
            except Exception as e:
                logger.error(f"❌ Error receiving message: {e}")
                await trio.sleep(1)

    async def _send_messages(self) -> None:
        """Send messages from user input."""
        print(f"\n🎉 Welcome to DHT Messaging, {self.username}!")
        print("💡 Type messages to send to all connected peers")
        print("💡 Type 'quit' to exit")
        print("💡 Type 'peers' to see connected peers")
        print("💡 Type 'discover' to see discovered peers")
        print(f"\n{self.username}> ", end="", flush=True)
        
        while not self.termination_event.is_set():
            try:
                # Use trio's run_sync_in_worker_thread for non-blocking input
                user_input = await trio.to_thread.run_sync(input)
                
                if user_input.lower() == "quit":
                    self.termination_event.set()
                    break
                elif user_input.lower() == "peers":
                    connected_count = len(self.connected_peers)
                    print(f"🔗 Connected peers: {connected_count}")
                    for peer_id in self.connected_peers:
                        print(f"   - {peer_id.pretty()}")
                    print(f"{self.username}> ", end="", flush=True)
                elif user_input.lower() == "discover":
                    discovered_count = len(discovered_peers)
                    print(f"🔍 Discovered peers: {discovered_count}")
                    for peer_id in discovered_peers:
                        status = "✅" if peer_id in self.connected_peers else "⏳"
                        print(f"   {status} {peer_id.pretty()}")
                    print(f"{self.username}> ", end="", flush=True)
                elif user_input.strip():
                    # Send message
                    message = f"[{self.username}]: {user_input}"
                    await self.pubsub.publish(MESSAGING_TOPIC, message.encode())
                    print(f"📤 Sent: {user_input}")
                    print(f"{self.username}> ", end="", flush=True)
                else:
                    print(f"{self.username}> ", end="", flush=True)
                    
            except Exception as e:
                logger.error(f"❌ Error in send messages: {e}")
                await trio.sleep(1)

    async def _status_monitor(self) -> None:
        """Monitor and display node status."""
        while not self.termination_event.is_set():
            try:
                connected_count = len(self.connected_peers)
                discovered_count = len(discovered_peers)
                routing_peers = len(self.dht.routing_table.peers)
                
                if connected_count > 0 or discovered_count > 0:
                    logger.info(
                        f"📊 Status - Connected: {connected_count}, "
                        f"Discovered: {discovered_count}, "
                        f"Routing: {routing_peers}"
                    )
                
                await trio.sleep(30)  # Status every 30 seconds
                
            except Exception as e:
                logger.error(f"❌ Error in status monitor: {e}")
                await trio.sleep(30)

    def stop(self) -> None:
        """Stop the node."""
        self.termination_event.set()


async def run_dht_messaging(port: int, username: str = None) -> None:
    """Run the DHT messaging node."""
    node = DHTMessagingNode(port, username)
    try:
        await node.start()
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
        node.stop()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Decentralized Messaging with DHT Bootstrap - ETH Delhi Hackathon"
    )
    parser.add_argument(
        "-p", "--port", 
        type=int, 
        default=0,
        help="Port to listen on (0 for random)"
    )
    parser.add_argument(
        "-u", "--username",
        type=str,
        help="Username for this node"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.port == 0:
        args.port = find_free_port()
    
    logger.info("🚀 Starting DHT Messaging System")
    logger.info("🎯 ETH Delhi Hackathon - Decentralized Messaging with DHT Bootstrap")
    
    try:
        trio.run(run_dht_messaging, args.port, args.username)
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
    except Exception as e:
        logger.error(f"❌ Application failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python

"""
Advanced DHT Direct Messaging - ETH Delhi Hackathon

This example demonstrates direct peer-to-peer messaging using DHT for peer discovery.
Peers can find each other by peer ID through DHT lookups and establish direct
connections for private messaging without relying on pubsub topics.

Key Features:
- DHT-based peer discovery (no bootstrap servers)
- Direct peer-to-peer messaging
- Peer lookup by ID through DHT
- Private messaging channels
- Serverless architecture
"""

import argparse
import asyncio
import json
import logging
import secrets
import sys
import time
from typing import Dict, Optional, Set

import base58
import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.abc import IHost, INetStream
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.network.stream.exceptions import StreamClosed, StreamEOF, StreamReset
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.async_service import background_trio_service
from libp2p.utils.address_validation import find_free_port, get_available_interfaces

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("dht-direct-messaging")

# Protocol IDs
DIRECT_MESSAGING_PROTOCOL = TProtocol("/dht-direct-messaging/1.0.0")

# Global state
discovered_peers: Set[str] = set()
peer_discovery_event = trio.Event()
active_connections: Dict[str, INetStream] = {}


class DHTDirectMessagingNode:
    """
    A decentralized direct messaging node that uses DHT for peer discovery
    and direct streams for private messaging.
    """

    def __init__(self, port: int, username: str = None):
        self.port = port
        self.username = username or f"user_{secrets.token_hex(4)}"
        self.host: Optional[IHost] = None
        self.dht: Optional[KadDHT] = None
        self.termination_event = trio.Event()
        self.connected_peers: Set[str] = set()
        self.peer_usernames: Dict[str, str] = {}

    async def start(self) -> None:
        """Start the DHT direct messaging node."""
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

                logger.info(f"🚀 Starting DHT Direct Messaging Node: {self.username}")
                logger.info(f"📍 Peer ID: {self.host.get_id()}")
                logger.info(f"🌐 Listening on: {listen_addrs}")

                # Initialize DHT in SERVER mode for peer discovery
                self.dht = KadDHT(self.host, DHTMode.SERVER, enable_random_walk=True)

                # Set up stream handler for incoming direct messages
                self.host.set_stream_handler(DIRECT_MESSAGING_PROTOCOL, self._handle_incoming_stream)

                # Start services
                async with background_trio_service(self.dht):
                    logger.info("✅ DHT service started successfully")

                    # Start background tasks
                    nursery.start_soon(self._peer_discovery_loop)
                    nursery.start_soon(self._peer_connection_loop)
                    nursery.start_soon(self._user_interface_loop)
                    nursery.start_soon(self._status_monitor)

                    # Wait for termination
                    await self.termination_event.wait()

        except Exception as e:
            logger.error(f"❌ Error starting node: {e}")
            raise

    async def _handle_incoming_stream(self, stream: INetStream) -> None:
        """Handle incoming direct messaging streams."""
        try:
            peer_id = stream.muxed_conn.peer_id
            peer_id_str = peer_id.pretty()
            
            logger.info(f"📨 New direct message connection from {peer_id_str}")
            
            # Store the connection
            active_connections[peer_id_str] = stream
            
            # Start receiving messages from this peer
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._receive_direct_messages, stream, peer_id_str)
                
        except Exception as e:
            logger.error(f"❌ Error handling incoming stream: {e}")

    async def _receive_direct_messages(self, stream: INetStream, peer_id_str: str) -> None:
        """Receive direct messages from a specific peer."""
        try:
            while not self.termination_event.is_set():
                try:
                    # Read message length first
                    length_bytes = await stream.read(4)
                    if not length_bytes:
                        break
                    
                    message_length = int.from_bytes(length_bytes, 'big')
                    
                    # Read the actual message
                    message_bytes = await stream.read(message_length)
                    if not message_bytes:
                        break
                    
                    # Parse the message
                    message_data = json.loads(message_bytes.decode('utf-8'))
                    message_type = message_data.get('type')
                    
                    if message_type == 'message':
                        content = message_data.get('content', '')
                        sender_username = message_data.get('username', 'Unknown')
                        
                        # Store peer username
                        self.peer_usernames[peer_id_str] = sender_username
                        
                        print(f"\n💬 [{sender_username}]: {content}")
                        print(f"{self.username}> ", end="", flush=True)
                        
                    elif message_type == 'username':
                        username = message_data.get('username', 'Unknown')
                        self.peer_usernames[peer_id_str] = username
                        print(f"\n👤 {peer_id_str[:8]} is now known as {username}")
                        print(f"{self.username}> ", end="", flush=True)
                        
                except (StreamClosed, StreamEOF, StreamReset):
                    logger.info(f"📤 Connection closed with {peer_id_str}")
                    break
                except Exception as e:
                    logger.error(f"❌ Error receiving message from {peer_id_str}: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"❌ Error in receive direct messages: {e}")
        finally:
            # Clean up connection
            if peer_id_str in active_connections:
                del active_connections[peer_id_str]

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
                        peer_id_str = peer_id.pretty()
                        if peer_id_str not in discovered_peers:
                            discovered_peers.add(peer_id_str)
                            logger.info(f"➕ New peer discovered: {peer_id_str}")
                
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
                for peer_id_str in list(discovered_peers):
                    if peer_id_str not in self.connected_peers:
                        try:
                            # Convert string back to peer ID
                            peer_id = self.host.get_id().__class__.from_string(peer_id_str)
                            
                            # Get peer info from DHT
                            peer_info = await self.dht.peer_routing.find_peer(peer_id)
                            if peer_info:
                                logger.info(f"🔗 Attempting to connect to {peer_id_str}")
                                await self.host.connect(peer_info)
                                self.connected_peers.add(peer_id_str)
                                logger.info(f"✅ Connected to {peer_id_str}")
                                
                                # Send our username to the peer
                                await self._send_username_to_peer(peer_id)
                                
                            else:
                                logger.debug(f"⚠️  No peer info found for {peer_id_str}")
                        except Exception as e:
                            logger.debug(f"❌ Failed to connect to {peer_id_str}: {e}")
                
                await trio.sleep(10)  # Try connections every 10 seconds
                
            except Exception as e:
                logger.error(f"❌ Error in peer connection: {e}")
                await trio.sleep(10)

    async def _send_username_to_peer(self, peer_id) -> None:
        """Send our username to a peer."""
        try:
            stream = await self.host.new_stream(peer_id, [DIRECT_MESSAGING_PROTOCOL])
            
            # Send username message
            username_message = {
                'type': 'username',
                'username': self.username
            }
            
            message_bytes = json.dumps(username_message).encode('utf-8')
            length_bytes = len(message_bytes).to_bytes(4, 'big')
            
            await stream.write(length_bytes + message_bytes)
            
            # Store the connection
            peer_id_str = peer_id.pretty()
            active_connections[peer_id_str] = stream
            
            # Start receiving messages from this peer
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._receive_direct_messages, stream, peer_id_str)
                
        except Exception as e:
            logger.error(f"❌ Error sending username to {peer_id.pretty()}: {e}")

    async def _send_direct_message(self, peer_id_str: str, message: str) -> None:
        """Send a direct message to a specific peer."""
        try:
            if peer_id_str not in active_connections:
                logger.error(f"❌ No active connection to {peer_id_str}")
                return
            
            stream = active_connections[peer_id_str]
            
            # Create message
            message_data = {
                'type': 'message',
                'content': message,
                'username': self.username
            }
            
            message_bytes = json.dumps(message_data).encode('utf-8')
            length_bytes = len(message_bytes).to_bytes(4, 'big')
            
            await stream.write(length_bytes + message_bytes)
            print(f"📤 Sent to {peer_id_str[:8]}: {message}")
            
        except Exception as e:
            logger.error(f"❌ Error sending message to {peer_id_str}: {e}")

    async def _user_interface_loop(self) -> None:
        """Handle user interface and commands."""
        print(f"\n🎉 Welcome to DHT Direct Messaging, {self.username}!")
        print("💡 Commands:")
        print("   - 'msg <peer_id> <message>' - Send direct message")
        print("   - 'peers' - Show connected peers")
        print("   - 'discover' - Show discovered peers")
        print("   - 'quit' - Exit")
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
                        username = self.peer_usernames.get(peer_id, "Unknown")
                        print(f"   - {peer_id[:8]} ({username})")
                    print(f"{self.username}> ", end="", flush=True)
                elif user_input.lower() == "discover":
                    discovered_count = len(discovered_peers)
                    print(f"🔍 Discovered peers: {discovered_count}")
                    for peer_id in discovered_peers:
                        status = "✅" if peer_id in self.connected_peers else "⏳"
                        username = self.peer_usernames.get(peer_id, "Unknown")
                        print(f"   {status} {peer_id[:8]} ({username})")
                    print(f"{self.username}> ", end="", flush=True)
                elif user_input.startswith("msg "):
                    parts = user_input.split(" ", 2)
                    if len(parts) >= 3:
                        peer_id = parts[1]
                        message = parts[2]
                        await self._send_direct_message(peer_id, message)
                    else:
                        print("❌ Usage: msg <peer_id> <message>")
                    print(f"{self.username}> ", end="", flush=True)
                elif user_input.strip():
                    print("❌ Unknown command. Type 'quit' to exit.")
                    print(f"{self.username}> ", end="", flush=True)
                else:
                    print(f"{self.username}> ", end="", flush=True)
                    
            except Exception as e:
                logger.error(f"❌ Error in user interface: {e}")
                await trio.sleep(1)

    async def _status_monitor(self) -> None:
        """Monitor and display node status."""
        while not self.termination_event.is_set():
            try:
                connected_count = len(self.connected_peers)
                discovered_count = len(discovered_peers)
                routing_peers = len(self.dht.routing_table.peers)
                active_conns = len(active_connections)
                
                if connected_count > 0 or discovered_count > 0:
                    logger.info(
                        f"📊 Status - Connected: {connected_count}, "
                        f"Discovered: {discovered_count}, "
                        f"Routing: {routing_peers}, "
                        f"Active: {active_conns}"
                    )
                
                await trio.sleep(30)  # Status every 30 seconds
                
            except Exception as e:
                logger.error(f"❌ Error in status monitor: {e}")
                await trio.sleep(30)

    def stop(self) -> None:
        """Stop the node."""
        self.termination_event.set()


async def run_dht_direct_messaging(port: int, username: str = None) -> None:
    """Run the DHT direct messaging node."""
    node = DHTDirectMessagingNode(port, username)
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
        description="DHT Direct Messaging - ETH Delhi Hackathon"
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
    
    logger.info("🚀 Starting DHT Direct Messaging System")
    logger.info("🎯 ETH Delhi Hackathon - Direct Messaging with DHT Bootstrap")
    
    try:
        trio.run(run_dht_direct_messaging, args.port, args.username)
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
    except Exception as e:
        logger.error(f"❌ Application failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

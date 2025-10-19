"""
Decentralized Chat with Peer Reputation

A spam-resistant chat application using libp2p gossipsub with peer reputation tracking.
This implementation demonstrates how peer scoring and peerstore can be used to create
a resilient decentralized chat system.
"""

import argparse
import asyncio
import base58
import json
import logging
import sys
import time
from typing import Dict, List, Optional

import trio
from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port, get_available_interfaces

from .peer_reputation import PeerReputationManager, INITIAL_REPUTATION

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("decentralized_chat")

# Protocol and topic configuration
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
CHAT_TOPIC = "decentralized-chat-reputation"
USERNAME_KEY = "username"

class DecentralizedChat:
    """Main chat application with peer reputation system."""
    
    def __init__(self, username: str, port: Optional[int] = None):
        self.username = username
        self.port = port or find_free_port()
        self.host = None
        self.pubsub = None
        self.reputation_manager = None
        self.subscription = None
        self.running = False
        
        # Message tracking
        self.message_count = 0
        self.received_messages = 0
        self.blocked_messages = 0
        
        # Create key pair for this node
        self.key_pair = create_new_key_pair()
    
    async def start(self) -> None:
        """Start the chat application."""
        logger.info(f"Starting decentralized chat for user: {self.username}")
        
        # Create libp2p host
        listen_addrs = get_available_interfaces(self.port)
        self.host = new_host(
            key_pair=self.key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        
        # Initialize reputation manager
        self.reputation_manager = PeerReputationManager(self.host.get_peerstore())
        
        # Create and configure gossipsub
        gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=4,  # Number of peers to maintain in mesh
            degree_low=2,  # Lower bound for mesh peers
            degree_high=6,  # Upper bound for mesh peers
            time_to_live=300,  # 5 minutes TTL
            gossip_window=3,
            gossip_history=10,
            heartbeat_initial_delay=1.0,
            heartbeat_interval=10,  # More frequent for demo
        )
        
        # Create pubsub with custom validator
        self.pubsub = Pubsub(
            self.host,
            gossipsub,
            strict_signing=True,
        )
        
        # Add custom message validator
        self.pubsub.add_topic_validator(CHAT_TOPIC, self._message_validator)
        
        # Start the host and pubsub
        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                # Subscribe to chat topic
                self.subscription = await self.pubsub.subscribe(CHAT_TOPIC)
                
                # Start background tasks
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self._message_receiver)
                    nursery.start_soon(self._reputation_maintenance)
                    nursery.start_soon(self._stats_reporter)
                    
                    self.running = True
                    logger.info(f"Chat started! Listening on port {self.port}")
                    logger.info(f"Peer ID: {self.host.get_id()}")
                    
                    # Print connection info
                    addrs = self.host.get_addrs()
                    for addr in addrs:
                        logger.info(f"Address: {addr}")
                    
                    # Start user input loop
                    await self._user_input_loop()
    
    async def _message_validator(self, msg_forwarder, msg: rpc_pb2.Message) -> bool:
        """Custom message validator with reputation checking."""
        try:
            # Check if we should accept messages from this peer
            if not self.reputation_manager.should_accept_message(msg_forwarder):
                logger.warning(f"Blocking message from spam peer: {msg_forwarder}")
                self.blocked_messages += 1
                return False
            
            # Validate message content
            is_valid, reason = self.reputation_manager.check_message_validity(
                msg_forwarder, msg.data, CHAT_TOPIC
            )
            
            if not is_valid:
                logger.warning(f"Invalid message from {msg_forwarder}: {reason}")
                self.blocked_messages += 1
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error in message validator: {e}")
            return False
    
    async def _message_receiver(self) -> None:
        """Receive and display messages from the network."""
        while self.running:
            try:
                message = await self.subscription.get()
                self.received_messages += 1
                
                # Parse message data
                try:
                    message_data = json.loads(message.data.decode('utf-8'))
                    sender_username = message_data.get('username', 'Unknown')
                    message_text = message_data.get('message', '')
                    timestamp = message_data.get('timestamp', time.time())
                    
                    # Get sender's trust level
                    trust_level = self.reputation_manager.get_peer_trust_level(message.from_id)
                    
                    # Format message display based on trust level
                    if trust_level == "trusted":
                        color = "\x1b[32m"  # Green
                        trust_indicator = "✓"
                    elif trust_level == "spam":
                        color = "\x1b[31m"  # Red
                        trust_indicator = "⚠"
                    else:
                        color = "\x1b[33m"  # Yellow
                        trust_indicator = "?"
                    
                    # Display message
                    time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
                    print(f"{color}[{time_str}] {trust_indicator} {sender_username}: {message_text}\x1b[0m")
                    
                except json.JSONDecodeError:
                    logger.warning(f"Received invalid JSON message from {message.from_id}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
            except Exception as e:
                logger.error(f"Error in message receiver: {e}")
                await trio.sleep(1)
    
    async def _reputation_maintenance(self) -> None:
        """Maintain reputation system and apply decay."""
        while self.running:
            try:
                # Apply reputation decay
                self.reputation_manager.apply_reputation_decay()
                
                # Save reputation data to peerstore
                for peer_id in self.reputation_manager.reputations:
                    self.reputation_manager.save_reputation_to_peerstore(peer_id)
                
                await trio.sleep(3600)  # Run every hour
                
            except Exception as e:
                logger.error(f"Error in reputation maintenance: {e}")
                await trio.sleep(60)
    
    async def _stats_reporter(self) -> None:
        """Report network statistics periodically."""
        while self.running:
            try:
                await trio.sleep(30)  # Report every 30 seconds
                
                stats = self.reputation_manager.get_network_stats()
                logger.info(
                    f"Network Stats - Total: {stats['total_peers']}, "
                    f"Trusted: {stats['trusted_peers']}, "
                    f"Spam: {stats['spam_peers']}, "
                    f"Messages: {self.received_messages}, "
                    f"Blocked: {self.blocked_messages}"
                )
                
            except Exception as e:
                logger.error(f"Error in stats reporter: {e}")
    
    async def _user_input_loop(self) -> None:
        """Handle user input and send messages."""
        print(f"\nWelcome to Decentralized Chat, {self.username}!")
        print("Type your messages and press Enter to send.")
        print("Commands:")
        print("  /stats - Show network statistics")
        print("  /peers - Show peer information")
        print("  /quit - Exit the chat")
        print("-" * 50)
        
        async_f = trio.wrap_file(sys.stdin)
        
        while self.running:
            try:
                line = await async_f.readline()
                if not line:
                    break
                
                message_text = line.strip()
                
                if not message_text:
                    continue
                
                # Handle commands
                if message_text.startswith('/'):
                    await self._handle_command(message_text)
                    continue
                
                # Send message
                await self._send_message(message_text)
                
            except Exception as e:
                logger.error(f"Error in user input loop: {e}")
                break
    
    async def _handle_command(self, command: str) -> None:
        """Handle chat commands."""
        if command == '/stats':
            stats = self.reputation_manager.get_network_stats()
            print(f"\n=== Network Statistics ===")
            print(f"Total peers: {stats['total_peers']}")
            print(f"Trusted peers: {stats['trusted_peers']}")
            print(f"Spam peers: {stats['spam_peers']}")
            print(f"Neutral peers: {stats['neutral_peers']}")
            print(f"Messages received: {self.received_messages}")
            print(f"Messages blocked: {self.blocked_messages}")
            print(f"Messages sent: {self.message_count}")
            print("=" * 25)
            
        elif command == '/peers':
            print(f"\n=== Peer Information ===")
            for peer_id, reputation in self.reputation_manager.reputations.items():
                trust_level = self.reputation_manager.get_peer_trust_level(peer_id)
                peer_id_short = base58.b58encode(peer_id.to_bytes()).decode()[:8]
                print(f"Peer {peer_id_short}: {trust_level} (score: {reputation.score:.2f})")
            print("=" * 20)
            
        elif command == '/quit':
            print("Goodbye!")
            self.running = False
            
        else:
            print(f"Unknown command: {command}")
    
    async def _send_message(self, message_text: str) -> None:
        """Send a message to the chat."""
        try:
            # Create message data
            message_data = {
                'username': self.username,
                'message': message_text,
                'timestamp': time.time(),
                'peer_id': self.host.get_id().to_string()
            }
            
            # Publish message
            await self.pubsub.publish(CHAT_TOPIC, json.dumps(message_data).encode('utf-8'))
            self.message_count += 1
            
            # Show our own message
            time_str = time.strftime("%H:%M:%S", time.localtime())
            print(f"\x1b[36m[{time_str}] {self.username}: {message_text}\x1b[0m")
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
    
    async def connect_to_peer(self, peer_address: str) -> None:
        """Connect to a specific peer."""
        try:
            maddr = info_from_p2p_addr(peer_address)
            await self.host.connect(maddr)
            logger.info(f"Connected to peer: {peer_address}")
        except Exception as e:
            logger.error(f"Failed to connect to peer {peer_address}: {e}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Decentralized Chat with Peer Reputation - ETH-Delhi Implementation"
    )
    parser.add_argument(
        "-u", "--username", 
        required=True, 
        help="Your username in the chat"
    )
    parser.add_argument(
        "-p", "--port", 
        type=int, 
        help="Port to listen on (default: random free port)"
    )
    parser.add_argument(
        "-c", "--connect", 
        help="Connect to a specific peer (multiaddr format)"
    )
    
    args = parser.parse_args()
    
    # Create and start chat
    chat = DecentralizedChat(args.username, args.port)
    
    try:
        if args.connect:
            # Connect to peer first, then start chat
            await chat.connect_to_peer(args.connect)
        
        await chat.start()
        
    except KeyboardInterrupt:
        logger.info("Chat interrupted by user")
    except Exception as e:
        logger.error(f"Chat error: {e}")
    finally:
        chat.running = False


if __name__ == "__main__":
    trio.run(main)

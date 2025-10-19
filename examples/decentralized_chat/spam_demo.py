"""
Spam Demo for Decentralized Chat

This script demonstrates how the peer reputation system handles spam and bad actors.
It creates multiple chat instances with different behaviors to show the reputation
system in action.
"""

import asyncio
import json
import logging
import random
import time
from typing import List

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

from .peer_reputation import PeerReputationManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("spam_demo")

GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
CHAT_TOPIC = "decentralized-chat-reputation"

class ChatBot:
    """A chat bot that can exhibit different behaviors."""
    
    def __init__(self, name: str, behavior: str, port: int):
        self.name = name
        self.behavior = behavior  # "good", "spam", "flood", "duplicate"
        self.port = port
        self.host = None
        self.pubsub = None
        self.reputation_manager = None
        self.subscription = None
        self.running = False
        self.message_count = 0
        self.received_messages = 0
        self.blocked_messages = 0
        
        # Create key pair
        self.key_pair = create_new_key_pair()
        
        # Behavior-specific settings
        self._setup_behavior()
    
    def _setup_behavior(self):
        """Setup behavior-specific parameters."""
        if self.behavior == "spam":
            self.message_interval = 0.5  # Very frequent
            self.spam_messages = [
                "CLICK HERE FOR FREE MONEY!!!",
                "WIN NOW! LIMITED TIME OFFER!",
                "URGENT: ACT NOW OR MISS OUT!",
                "GUARANTEED PROFITS! NO RISK!",
                "MAKE MONEY FAST! CLICK HERE!"
            ]
        elif self.behavior == "flood":
            self.message_interval = 0.1  # Extremely frequent
            self.flood_messages = [f"Flood message {i}" for i in range(100)]
        elif self.behavior == "duplicate":
            self.message_interval = 1.0
            self.duplicate_message = "This is a duplicate message that I keep sending"
        else:  # good behavior
            self.message_interval = 5.0
            self.good_messages = [
                "Hello everyone!",
                "How is everyone doing today?",
                "This is a great chat system!",
                "I'm learning about decentralized networks",
                "The reputation system is really interesting",
                "Thanks for the great conversation!",
                "I hope everyone is having a good day",
                "This demo is very educational"
            ]
    
    async def start(self, connect_to: str = None):
        """Start the chat bot."""
        logger.info(f"Starting {self.name} ({self.behavior} behavior) on port {self.port}")
        
        # Create host
        listen_addrs = get_available_interfaces(self.port)
        self.host = new_host(
            key_pair=self.key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        
        # Initialize reputation manager
        self.reputation_manager = PeerReputationManager(self.host.get_peerstore())
        
        # Create gossipsub
        gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=4,
            degree_low=2,
            degree_high=6,
            time_to_live=300,
            gossip_window=3,
            gossip_history=10,
            heartbeat_initial_delay=1.0,
            heartbeat_interval=10,
        )
        
        # Create pubsub
        self.pubsub = Pubsub(
            self.host,
            gossipsub,
            strict_signing=True,
        )
        
        # Add validator
        self.pubsub.add_topic_validator(CHAT_TOPIC, self._message_validator)
        
        # Start host and pubsub
        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                # Connect to other peer if specified
                if connect_to:
                    try:
                        maddr = info_from_p2p_addr(connect_to)
                        await self.host.connect(maddr)
                        logger.info(f"{self.name} connected to {connect_to}")
                    except Exception as e:
                        logger.error(f"{self.name} failed to connect: {e}")
                
                # Subscribe to topic
                self.subscription = await self.pubsub.subscribe(CHAT_TOPIC)
                
                # Start tasks
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self._message_receiver)
                    nursery.start_soon(self._message_sender)
                    nursery.start_soon(self._stats_reporter)
                    
                    self.running = True
                    logger.info(f"{self.name} is running!")
                    
                    # Keep running
                    await trio.sleep_forever()
    
    async def _message_validator(self, msg_forwarder, msg: rpc_pb2.Message) -> bool:
        """Message validator with reputation checking."""
        try:
            if not self.reputation_manager.should_accept_message(msg_forwarder):
                self.blocked_messages += 1
                return False
            
            is_valid, reason = self.reputation_manager.check_message_validity(
                msg_forwarder, msg.data, CHAT_TOPIC
            )
            
            if not is_valid:
                self.blocked_messages += 1
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"{self.name} validator error: {e}")
            return False
    
    async def _message_receiver(self):
        """Receive and log messages."""
        while self.running:
            try:
                message = await self.subscription.get()
                self.received_messages += 1
                
                try:
                    message_data = json.loads(message.data.decode('utf-8'))
                    sender = message_data.get('username', 'Unknown')
                    message_text = message_data.get('message', '')
                    
                    # Get trust level
                    trust_level = self.reputation_manager.get_peer_trust_level(message.from_id)
                    
                    logger.info(f"{self.name} received from {sender} ({trust_level}): {message_text[:50]}...")
                    
                except Exception as e:
                    logger.error(f"{self.name} error processing message: {e}")
                    
            except Exception as e:
                logger.error(f"{self.name} receiver error: {e}")
                await trio.sleep(1)
    
    async def _message_sender(self):
        """Send messages based on behavior."""
        await trio.sleep(2)  # Wait a bit before starting
        
        while self.running:
            try:
                if self.behavior == "spam":
                    message = random.choice(self.spam_messages)
                elif self.behavior == "flood":
                    message = random.choice(self.flood_messages)
                elif self.behavior == "duplicate":
                    message = self.duplicate_message
                else:  # good
                    message = random.choice(self.good_messages)
                
                await self._send_message(message)
                self.message_count += 1
                
                await trio.sleep(self.message_interval)
                
            except Exception as e:
                logger.error(f"{self.name} sender error: {e}")
                await trio.sleep(1)
    
    async def _send_message(self, message_text: str):
        """Send a message."""
        try:
            message_data = {
                'username': self.name,
                'message': message_text,
                'timestamp': time.time(),
                'peer_id': self.host.get_id().to_string()
            }
            
            await self.pubsub.publish(CHAT_TOPIC, json.dumps(message_data).encode('utf-8'))
            
        except Exception as e:
            logger.error(f"{self.name} send error: {e}")
    
    async def _stats_reporter(self):
        """Report statistics periodically."""
        while self.running:
            try:
                await trio.sleep(15)  # Report every 15 seconds
                
                stats = self.reputation_manager.get_network_stats()
                logger.info(
                    f"{self.name} Stats - Sent: {self.message_count}, "
                    f"Received: {self.received_messages}, "
                    f"Blocked: {self.blocked_messages}, "
                    f"Network peers: {stats['total_peers']}, "
                    f"Trusted: {stats['trusted_peers']}, "
                    f"Spam: {stats['spam_peers']}"
                )
                
            except Exception as e:
                logger.error(f"{self.name} stats error: {e}")


async def run_spam_demo():
    """Run the spam demonstration."""
    logger.info("Starting Spam Demo for Decentralized Chat")
    logger.info("This demo shows how the reputation system handles different peer behaviors")
    
    # Create bots with different behaviors
    bots = [
        ChatBot("Alice", "good", find_free_port()),
        ChatBot("Bob", "good", find_free_port()),
        ChatBot("Spammer", "spam", find_free_port()),
        ChatBot("Flooder", "flood", find_free_port()),
        ChatBot("Duplicator", "duplicate", find_free_port()),
    ]
    
    # Start the first bot (Alice)
    alice = bots[0]
    alice_task = trio.start_soon(alice.start)
    
    # Get Alice's address
    await trio.sleep(2)
    alice_addrs = alice.host.get_addrs()
    alice_addr = f"{alice_addrs[0]}/p2p/{alice.host.get_id()}"
    logger.info(f"Alice's address: {alice_addr}")
    
    # Start other bots and connect them to Alice
    bot_tasks = [alice_task]
    
    for bot in bots[1:]:
        task = trio.start_soon(bot.start, alice_addr)
        bot_tasks.append(task)
        await trio.sleep(1)  # Stagger connections
    
    logger.info("All bots started! Watch how the reputation system handles different behaviors:")
    logger.info("- Alice and Bob: Good behavior, should maintain high reputation")
    logger.info("- Spammer: Sends spam messages, should get down-scored")
    logger.info("- Flooder: Sends too many messages, should get rate-limited")
    logger.info("- Duplicator: Sends duplicate messages, should get penalized")
    logger.info("\nThe demo will run for 2 minutes...")
    
    # Let the demo run
    await trio.sleep(120)  # 2 minutes
    
    # Stop all bots
    logger.info("Stopping demo...")
    for bot in bots:
        bot.running = False
    
    # Wait for tasks to complete
    for task in bot_tasks:
        task.cancel()
    
    logger.info("Demo completed!")


if __name__ == "__main__":
    trio.run(run_spam_demo)

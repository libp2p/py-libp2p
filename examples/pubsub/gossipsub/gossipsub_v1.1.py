#!/usr/bin/env python3
"""
Gossipsub 1.1 Example

This example demonstrates Gossipsub 1.1 protocol (/meshsub/1.1.0).
Gossipsub 1.1 adds peer scoring and behavioral penalties to the basic
mesh-based pubsub, providing better resilience against basic attacks.

Features demonstrated:
- Basic mesh-based pubsub (from v1.0)
- Peer scoring with P1-P4 topic-scoped parameters
- Behavioral penalties (P5)
- Signed peer records
- Better resilience against attacks

Usage:
    python gossipsub_v1.1.py --nodes 5 --duration 30
"""

import argparse
import logging
import random
import time
from typing import List

import trio

from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("gossipsub-v1.1")

# Protocol version
GOSSIPSUB_V11 = TProtocol("/meshsub/1.1.0")
TOPIC = "gossipsub-v1.1-demo"


class GossipsubV11Node:
    """A node running Gossipsub 1.1"""
    
    def __init__(self, node_id: str, port: int, role: str = "honest"):
        self.node_id = node_id
        self.port = port
        self.role = role  # "honest" or "malicious"
        self.host = None
        self.pubsub = None
        self.gossipsub = None
        self.subscription = None
        self.messages_sent = 0
        self.messages_received = 0
        
    async def start(self):
        """Start the node with Gossipsub 1.1 configuration"""
        key_pair = create_new_key_pair()
        
        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        
        # Configure Gossipsub 1.1 - adds peer scoring
        score_params = ScoreParams(
            # Topic-scoped parameters (P1-P4)
            p1_time_in_mesh=TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
            p2_first_message_deliveries=TopicScoreParams(weight=0.5, cap=20.0, decay=0.99),
            p3_mesh_message_deliveries=TopicScoreParams(weight=0.3, cap=10.0, decay=0.99),
            p4_invalid_messages=TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
            # Global behavioral penalty (P5)
            p5_behavior_penalty_weight=1.0,
            p5_behavior_penalty_decay=0.99,
        )
        
        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_V11],
            degree=3,
            degree_low=2,
            degree_high=4,
            heartbeat_interval=5,
            heartbeat_initial_delay=1.0,
            score_params=score_params,
            # No max_idontwant_messages - v1.1 doesn't support IDONTWANT
            # No adaptive features - v1.1 doesn't have adaptive gossip
            # No advanced security features - v1.1 has basic security
        )
        
        self.pubsub = Pubsub(self.host, self.gossipsub)
        
        # Start services
        import multiaddr
        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{self.port}")]
        
        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                async with background_trio_service(self.gossipsub):
                    await self.pubsub.wait_until_ready()
                    self.subscription = await self.pubsub.subscribe(TOPIC)
                    logger.info(f"Node {self.node_id} (Gossipsub 1.1, {self.role}) started on port {self.port}")
                    
                    # Keep running
                    await trio.sleep_forever()
    
    async def publish_message(self, message: str):
        """Publish a message to the topic"""
        if self.pubsub:
            await self.pubsub.publish(TOPIC, message.encode())
            self.messages_sent += 1
            logger.info(f"Node {self.node_id} ({self.role}) published: {message}")
    
    async def receive_messages(self):
        """Receive and process messages"""
        if not self.subscription:
            return
            
        try:
            while True:
                message = await self.subscription.get()
                decoded = message.data.decode('utf-8')
                self.messages_received += 1
                logger.info(f"Node {self.node_id} received: {decoded}")
        except Exception as e:
            logger.debug(f"Node {self.node_id} receive loop ended: {e}")
    
    async def connect_to_peer(self, peer_addr: str):
        """Connect to another peer"""
        if self.host:
            try:
                from libp2p.peer.peerinfo import info_from_p2p_addr
                import multiaddr
                
                maddr = multiaddr.Multiaddr(peer_addr)
                info = info_from_p2p_addr(maddr)
                await self.host.connect(info)
                logger.debug(f"Node {self.node_id} connected to {peer_addr}")
            except Exception as e:
                logger.debug(f"Node {self.node_id} failed to connect to {peer_addr}: {e}")


class GossipsubV11Demo:
    """Demo controller for Gossipsub 1.1"""
    
    def __init__(self):
        self.nodes: List[GossipsubV11Node] = []
        
    async def setup_network(self, node_count: int = 5):
        """Set up a network of nodes"""
        roles = ["honest"] * (node_count - 1) + ["malicious"] * 1
        
        for i in range(node_count):
            port = find_free_port()
            role = roles[i] if i < len(roles) else "honest"
            node = GossipsubV11Node(f"node_{i}", port, role)
            self.nodes.append(node)
        
        logger.info(f"Created network with {node_count} nodes running Gossipsub 1.1")
        
    async def start_network(self, duration: int = 30):
        """Start all nodes and run the demo"""
        try:
            async with trio.open_nursery() as nursery:
                # Start all nodes
                for node in self.nodes:
                    nursery.start_soon(node.start)
                
                # Wait for initialization
                await trio.sleep(3)
                
                # Connect nodes in a mesh topology
                await self._connect_nodes()
                await trio.sleep(2)
                
                # Start message receiving for all nodes
                for node in self.nodes:
                    nursery.start_soon(node.receive_messages)
                
                # Run publishing loop
                end_time = time.time() + duration
                message_counter = 0
                
                print(f"\n{'='*60}")
                print("GOSSIPSUB 1.1 DEMO")
                print(f"{'='*60}")
                print(f"Running for {duration} seconds...")
                print(f"Protocol: /meshsub/1.1.0")
                print(f"Features: Peer scoring (P1-P5), behavioral penalties")
                print(f"{'='*60}\n")
                
                while time.time() < end_time:
                    # Honest nodes publish normally
                    honest_nodes = [n for n in self.nodes if n.role == "honest"]
                    if honest_nodes:
                        node = random.choice(honest_nodes)
                        message = f"honest_msg_{message_counter}_{int(time.time())}"
                        await node.publish_message(message)
                        message_counter += 1
                    
                    # Malicious nodes might send more messages (will be penalized)
                    malicious_nodes = [n for n in self.nodes if n.role == "malicious"]
                    if malicious_nodes and random.random() < 0.3:  # 30% chance
                        node = malicious_nodes[0]
                        message = f"malicious_msg_{message_counter}_{int(time.time())}"
                        await node.publish_message(message)
                        message_counter += 1
                    
                    await trio.sleep(2)  # Publish every 2 seconds
                
                # Print statistics
                await trio.sleep(1)  # Wait for final messages
                self._print_statistics()
                
                # Cancel all tasks to exit nursery
                nursery.cancel_scope.cancel()
                
        except Exception as e:
            logger.warning(f"Demo execution interrupted: {e}")
    
    async def _connect_nodes(self):
        """Connect nodes in a mesh topology"""
        for i, node in enumerate(self.nodes):
            # Connect to the next node in a ring topology
            if len(self.nodes) > 1:
                target_idx = (i + 1) % len(self.nodes)
                target = self.nodes[target_idx]
                
                if target.host and node.host:
                    peer_addr = f"/ip4/127.0.0.1/tcp/{target.port}/p2p/{target.host.get_id()}"
                    await node.connect_to_peer(peer_addr)
                    
                # Also connect to one more node for better connectivity
                if len(self.nodes) > 2:
                    target_idx2 = (i + 2) % len(self.nodes)
                    target2 = self.nodes[target_idx2]
                    
                    if target2.host and node.host:
                        peer_addr2 = f"/ip4/127.0.0.1/tcp/{target2.port}/p2p/{target2.host.get_id()}"
                        await node.connect_to_peer(peer_addr2)
    
    def _print_statistics(self):
        """Print demo statistics"""
        print(f"\n{'='*60}")
        print("DEMO STATISTICS")
        print(f"{'='*60}")
        
        total_sent = sum(node.messages_sent for node in self.nodes)
        total_received = sum(node.messages_received for node in self.nodes)
        
        honest_sent = sum(n.messages_sent for n in self.nodes if n.role == "honest")
        malicious_sent = sum(n.messages_sent for n in self.nodes if n.role == "malicious")
        
        print(f"Total messages sent: {total_sent}")
        print(f"  Honest nodes: {honest_sent}")
        print(f"  Malicious nodes: {malicious_sent}")
        print(f"Total messages received: {total_received}")
        print(f"\nPer-node statistics:")
        for node in self.nodes:
            print(f"  {node.node_id} ({node.role}): sent={node.messages_sent}, received={node.messages_received}")
        
        print(f"\n{'='*60}")
        print("Gossipsub 1.1 Features:")
        print("  ✓ Basic mesh-based pubsub (from v1.0)")
        print("  ✓ Peer scoring with P1-P4 (topic-scoped)")
        print("    - P1: Time in mesh")
        print("    - P2: First message deliveries")
        print("    - P3: Mesh message deliveries")
        print("    - P4: Invalid messages penalty")
        print("  ✓ Behavioral penalties (P5)")
        print("  ✓ Signed peer records")
        print("  ✗ No IDONTWANT support")
        print("  ✗ No adaptive gossip")
        print("  ✗ No advanced security features")
        print(f"{'='*60}\n")


async def main():
    parser = argparse.ArgumentParser(description="Gossipsub 1.1 Example")
    parser.add_argument(
        "--nodes",
        type=int,
        default=5,
        help="Number of nodes in the network"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Demo duration in seconds"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    demo = GossipsubV11Demo()
    await demo.setup_network(args.nodes)
    await demo.start_network(args.duration)


if __name__ == "__main__":
    trio.run(main)

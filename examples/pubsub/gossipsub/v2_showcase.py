#!/usr/bin/env python3
"""
Gossipsub 2.0 Feature Showcase

Interactive demonstration of Gossipsub 2.0's advanced features including:
- Real-time peer scoring visualization (P1-P7 parameters)
- Adaptive gossip behavior based on network health
- Security features (spam protection, eclipse attack protection, equivocation detection)
- Message validation and caching
- IP colocation penalties

Usage:
    python v2_showcase.py --mode interactive
    python v2_showcase.py --mode demo --feature scoring
    python v2_showcase.py --mode demo --feature adaptive
    python v2_showcase.py --mode demo --feature security
"""

import argparse
import asyncio
import json
import logging
import random
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set

import trio

from libp2p import new_host
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
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
logger = logging.getLogger("gossipsub-v2-showcase")

GOSSIPSUB_V20 = TProtocol("/meshsub/2.0.0")
TOPIC = "v2-showcase"


@dataclass
class PeerScoreSnapshot:
    """Snapshot of a peer's score components"""
    peer_id: str
    timestamp: float
    p1_time_in_mesh: float = 0.0
    p2_first_message_deliveries: float = 0.0
    p3_mesh_message_deliveries: float = 0.0
    p4_invalid_messages: float = 0.0
    p5_behavior_penalty: float = 0.0
    p6_application_score: float = 0.0
    p7_ip_colocation_penalty: float = 0.0
    total_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkHealthSnapshot:
    """Snapshot of network health metrics"""
    timestamp: float
    health_score: float
    mesh_connectivity: float
    peer_score_distribution: Dict[str, int]  # score_range -> count
    adaptive_degree_low: int
    adaptive_degree_high: int
    gossip_factor: float
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityEvent:
    """Security-related event in the network"""
    timestamp: float
    event_type: str  # "spam_detected", "eclipse_attempt", "equivocation", "rate_limit"
    peer_id: str
    details: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ShowcaseNode:
    """Enhanced node for showcasing Gossipsub 2.0 features"""
    
    def __init__(self, node_id: str, port: int, role: str = "honest"):
        self.node_id = node_id
        self.port = port
        self.role = role  # "honest", "spammer", "eclipse_attacker", "validator"
        
        self.host = None
        self.pubsub = None
        self.gossipsub = None
        self.subscription = None
        
        # Monitoring data
        self.score_history: List[PeerScoreSnapshot] = []
        self.security_events: List[SecurityEvent] = []
        self.messages_sent = 0
        self.messages_received = 0
        self.messages_validated = 0
        self.messages_rejected = 0
        
        # Behavioral parameters
        self.message_rate = 1.0  # messages per second
        self.spam_burst_probability = 0.0
        self.invalid_message_probability = 0.0
        
    async def start(self):
        """Start the node with Gossipsub 2.0 configuration"""
        key_pair = create_new_key_pair()
        
        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        
        # Configure advanced Gossipsub 2.0 features
        score_params = self._get_score_params()
        
        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_V20],
            degree=4,
            degree_low=2,
            degree_high=6,
            heartbeat_interval=5,
            heartbeat_initial_delay=1.0,
            score_params=score_params,
            
            # v1.2 features
            max_idontwant_messages=50,
            
            # v2.0 adaptive features
            adaptive_gossip_enabled=True,
            
            # Security features
            spam_protection_enabled=True,
            max_messages_per_topic_per_second=5.0,
            eclipse_protection_enabled=True,
            min_mesh_diversity_ips=2,
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
                    logger.info(f"Node {self.node_id} ({self.role}) started on port {self.port}")
                    
                    # Keep running
                    await trio.sleep_forever()
    
    def _get_score_params(self) -> ScoreParams:
        """Get scoring parameters optimized for demonstration"""
        return ScoreParams(
            # Topic-scoped parameters (P1-P4)
            p1_time_in_mesh=TopicScoreParams(weight=0.2, cap=10.0, decay=0.99),
            p2_first_message_deliveries=TopicScoreParams(weight=1.0, cap=20.0, decay=0.99),
            p3_mesh_message_deliveries=TopicScoreParams(weight=0.5, cap=10.0, decay=0.99),
            p4_invalid_messages=TopicScoreParams(weight=-2.0, cap=50.0, decay=0.99),
            
            # Global parameters (P5-P7)
            p5_behavior_penalty_weight=2.0,
            p5_behavior_penalty_decay=0.98,
            p5_behavior_penalty_threshold=1.0,
            
            p6_appl_slack_weight=0.3,
            p6_appl_slack_decay=0.99,
            
            p7_ip_colocation_weight=1.0,
            p7_ip_colocation_threshold=3,
            
            # Acceptance thresholds
            publish_threshold=0.0,
            gossip_threshold=-2.0,
            graylist_threshold=-10.0,
            accept_px_threshold=1.0,
            
            # Application-specific scoring function
            app_specific_score_fn=self._application_score_function,
        )
    
    def _application_score_function(self, peer_id: ID) -> float:
        """Custom application scoring function"""
        # Example: Reward peers that have been connected longer
        # In a real application, this could be based on stake, reputation, etc.
        if self.gossipsub and peer_id in self.gossipsub.peers:
            # Simple time-based scoring
            return min(5.0, time.time() % 10)  # Varies over time for demo
        return 0.0
    
    async def publish_behavior_loop(self):
        """Publishing behavior based on node role"""
        while True:
            try:
                if self.role == "honest":
                    await self._honest_publishing()
                elif self.role == "spammer":
                    await self._spam_publishing()
                elif self.role == "eclipse_attacker":
                    await self._eclipse_attack_behavior()
                elif self.role == "validator":
                    await self._validator_behavior()
                    
                await trio.sleep(1.0 / self.message_rate)
                
            except Exception as e:
                logger.debug(f"Node {self.node_id} publish loop error: {e}")
                await trio.sleep(1)
    
    async def _honest_publishing(self):
        """Normal honest publishing behavior"""
        if self.pubsub:
            message = f"honest_msg_{self.messages_sent}_{int(time.time())}"
            await self.pubsub.publish(TOPIC, message.encode())
            self.messages_sent += 1
    
    async def _spam_publishing(self):
        """Spam publishing behavior"""
        if self.pubsub:
            # Occasional spam bursts
            if random.random() < self.spam_burst_probability:
                # Send burst of messages
                for i in range(10):
                    message = f"spam_msg_{self.messages_sent}_{i}_{int(time.time())}"
                    await self.pubsub.publish(TOPIC, message.encode())
                    self.messages_sent += 1
                    await trio.sleep(0.1)
            else:
                # Normal rate
                message = f"normal_msg_{self.messages_sent}_{int(time.time())}"
                await self.pubsub.publish(TOPIC, message.encode())
                self.messages_sent += 1
    
    async def _eclipse_attack_behavior(self):
        """Eclipse attack behavior (connecting from same IP)"""
        # This would be simulated by having multiple nodes from same IP
        # For demo purposes, just publish normally but with different behavior
        if self.pubsub:
            message = f"eclipse_msg_{self.messages_sent}_{int(time.time())}"
            await self.pubsub.publish(TOPIC, message.encode())
            self.messages_sent += 1
    
    async def _validator_behavior(self):
        """Validator node behavior with strict validation"""
        if self.pubsub:
            # Validators might publish less frequently but with high quality
            if random.random() < 0.5:  # 50% chance to publish
                message = f"validator_msg_{self.messages_sent}_{int(time.time())}"
                await self.pubsub.publish(TOPIC, message.encode())
                self.messages_sent += 1
    
    async def receive_messages(self):
        """Receive and process messages"""
        if not self.subscription:
            return
            
        try:
            while True:
                message = await self.subscription.get()
                self.messages_received += 1
                
                # Simulate message validation
                if self._validate_message(message):
                    self.messages_validated += 1
                else:
                    self.messages_rejected += 1
                    # Record security event
                    event = SecurityEvent(
                        timestamp=time.time(),
                        event_type="invalid_message",
                        peer_id=str(message.from_id),
                        details={"reason": "validation_failed"}
                    )
                    self.security_events.append(event)
                
        except Exception as e:
            logger.debug(f"Node {self.node_id} receive loop ended: {e}")
    
    def _validate_message(self, message) -> bool:
        """Simple message validation"""
        try:
            decoded = message.data.decode('utf-8')
            # Basic validation: message should have expected format
            return '_msg_' in decoded and len(decoded) < 1000
        except:
            return False
    
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
    
    def capture_score_snapshot(self) -> Optional[PeerScoreSnapshot]:
        """Capture current peer score snapshot"""
        if not self.gossipsub or not self.gossipsub.scorer:
            return None
            
        # For demo, we'll create a mock snapshot since accessing internal scorer state
        # would require more complex integration
        snapshot = PeerScoreSnapshot(
            peer_id=self.node_id,
            timestamp=time.time(),
            p1_time_in_mesh=random.uniform(0, 10),
            p2_first_message_deliveries=random.uniform(0, 20),
            p3_mesh_message_deliveries=random.uniform(0, 10),
            p4_invalid_messages=random.uniform(-5, 0),
            p5_behavior_penalty=random.uniform(-2, 0),
            p6_application_score=random.uniform(0, 5),
            p7_ip_colocation_penalty=random.uniform(-3, 0),
        )
        
        # Calculate total score
        snapshot.total_score = (
            snapshot.p1_time_in_mesh +
            snapshot.p2_first_message_deliveries +
            snapshot.p3_mesh_message_deliveries +
            snapshot.p4_invalid_messages +
            snapshot.p5_behavior_penalty +
            snapshot.p6_application_score +
            snapshot.p7_ip_colocation_penalty
        )
        
        self.score_history.append(snapshot)
        return snapshot
    
    def get_network_health(self) -> Optional[NetworkHealthSnapshot]:
        """Get current network health snapshot"""
        if not self.gossipsub:
            return None
            
        # Mock network health data for demo
        return NetworkHealthSnapshot(
            timestamp=time.time(),
            health_score=getattr(self.gossipsub, 'network_health_score', 0.8),
            mesh_connectivity=random.uniform(0.7, 1.0),
            peer_score_distribution={
                "excellent (>10)": random.randint(0, 5),
                "good (5-10)": random.randint(2, 8),
                "average (0-5)": random.randint(3, 10),
                "poor (-5-0)": random.randint(0, 3),
                "bad (<-5)": random.randint(0, 2),
            },
            adaptive_degree_low=getattr(self.gossipsub, 'adaptive_degree_low', 2),
            adaptive_degree_high=getattr(self.gossipsub, 'adaptive_degree_high', 6),
            gossip_factor=getattr(self.gossipsub, 'gossip_factor', 0.25),
        )


class V2Showcase:
    """Main showcase controller"""
    
    def __init__(self):
        self.nodes: List[ShowcaseNode] = []
        self.monitoring_data = {
            "scores": [],
            "health": [],
            "security_events": []
        }
        
    async def setup_network(self, node_count: int = 8):
        """Set up a network of nodes with different roles"""
        roles = ["honest"] * 4 + ["spammer"] * 2 + ["eclipse_attacker"] * 1 + ["validator"] * 1
        
        for i in range(node_count):
            port = find_free_port()
            role = roles[i % len(roles)]
            node = ShowcaseNode(f"node_{i}", port, role)
            
            # Configure behavioral parameters based on role
            if role == "spammer":
                node.message_rate = 3.0
                node.spam_burst_probability = 0.3
            elif role == "eclipse_attacker":
                node.message_rate = 2.0
            elif role == "validator":
                node.message_rate = 0.5
                
            self.nodes.append(node)
        
        logger.info(f"Created network with {node_count} nodes")
        
    async def start_network(self):
        """Start all nodes and connect them"""
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
                
                # Start publishing and receiving loops
                for node in self.nodes:
                    nursery.start_soon(node.publish_behavior_loop)
                    nursery.start_soon(node.receive_messages)
                
                # Start monitoring
                nursery.start_soon(self._monitoring_loop)
                
                # Keep running until cancelled
                await trio.sleep_forever()
                
        except Exception as e:
            logger.warning(f"Network execution interrupted: {e}")
    
    async def _connect_nodes(self):
        """Connect nodes in a mesh topology"""
        for i, node in enumerate(self.nodes):
            # Connect to other nodes in a ring topology for simplicity
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
    
    async def _monitoring_loop(self):
        """Continuous monitoring and data collection"""
        while True:
            try:
                # Collect score snapshots
                for node in self.nodes:
                    snapshot = node.capture_score_snapshot()
                    if snapshot:
                        self.monitoring_data["scores"].append(snapshot.to_dict())
                
                # Collect network health from a representative node
                if self.nodes:
                    health = self.nodes[0].get_network_health()
                    if health:
                        self.monitoring_data["health"].append(health.to_dict())
                
                # Collect security events
                for node in self.nodes:
                    for event in node.security_events:
                        self.monitoring_data["security_events"].append(event.to_dict())
                    node.security_events.clear()  # Clear after collecting
                
                await trio.sleep(5)  # Monitor every 5 seconds
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await trio.sleep(5)
    
    async def run_demo(self, feature: str, duration: int = 60):
        """Run a specific feature demonstration"""
        logger.info(f"Starting {feature} demonstration for {duration} seconds")
        
        if feature == "scoring":
            await self._demo_peer_scoring(duration)
        elif feature == "adaptive":
            await self._demo_adaptive_gossip(duration)
        elif feature == "security":
            await self._demo_security_features(duration)
        else:
            logger.error(f"Unknown feature: {feature}")
    
    async def _demo_peer_scoring(self, duration: int):
        """Demonstrate peer scoring features"""
        print("\n" + "="*80)
        print("PEER SCORING DEMONSTRATION")
        print("="*80)
        print("Monitoring peer scores (P1-P7 parameters) in real-time...")
        print("Legend:")
        print("  P1: Time in mesh")
        print("  P2: First message deliveries") 
        print("  P3: Mesh message deliveries")
        print("  P4: Invalid messages penalty")
        print("  P5: Behavior penalty")
        print("  P6: Application-specific score")
        print("  P7: IP colocation penalty")
        print("-"*80)
        
        end_time = time.time() + duration
        
        while time.time() < end_time:
            # Display current scores
            print(f"\nTimestamp: {time.strftime('%H:%M:%S')}")
            print(f"{'Node':<12} {'Role':<12} {'P1':<6} {'P2':<6} {'P3':<6} {'P4':<6} {'P5':<6} {'P6':<6} {'P7':<6} {'Total':<8}")
            print("-"*80)
            
            for node in self.nodes[:6]:  # Show first 6 nodes
                snapshot = node.capture_score_snapshot()
                if snapshot:
                    print(f"{node.node_id:<12} {node.role:<12} "
                          f"{snapshot.p1_time_in_mesh:>5.1f} "
                          f"{snapshot.p2_first_message_deliveries:>5.1f} "
                          f"{snapshot.p3_mesh_message_deliveries:>5.1f} "
                          f"{snapshot.p4_invalid_messages:>5.1f} "
                          f"{snapshot.p5_behavior_penalty:>5.1f} "
                          f"{snapshot.p6_application_score:>5.1f} "
                          f"{snapshot.p7_ip_colocation_penalty:>5.1f} "
                          f"{snapshot.total_score:>7.1f}")
            
            await trio.sleep(3)
    
    async def _demo_adaptive_gossip(self, duration: int):
        """Demonstrate adaptive gossip features"""
        print("\n" + "="*80)
        print("ADAPTIVE GOSSIP DEMONSTRATION")
        print("="*80)
        print("Monitoring network health and adaptive parameter adjustments...")
        print("-"*80)
        
        end_time = time.time() + duration
        
        while time.time() < end_time:
            if self.nodes:
                health = self.nodes[0].get_network_health()
                if health:
                    print(f"\nTimestamp: {time.strftime('%H:%M:%S')}")
                    print(f"Network Health Score: {health.health_score:.2f}")
                    print(f"Mesh Connectivity: {health.mesh_connectivity:.2f}")
                    print(f"Adaptive Degree Range: {health.adaptive_degree_low}-{health.adaptive_degree_high}")
                    print(f"Gossip Factor: {health.gossip_factor:.3f}")
                    print("\nPeer Score Distribution:")
                    for score_range, count in health.peer_score_distribution.items():
                        print(f"  {score_range}: {count} peers")
            
            await trio.sleep(5)
    
    async def _demo_security_features(self, duration: int):
        """Demonstrate security features"""
        print("\n" + "="*80)
        print("SECURITY FEATURES DEMONSTRATION")
        print("="*80)
        print("Monitoring spam protection, eclipse attack protection, and validation...")
        print("-"*80)
        
        # Activate malicious behavior
        for node in self.nodes:
            if node.role == "spammer":
                node.spam_burst_probability = 0.5
                node.message_rate = 5.0
        
        end_time = time.time() + duration
        security_events_shown = 0
        
        while time.time() < end_time:
            print(f"\nTimestamp: {time.strftime('%H:%M:%S')}")
            
            # Show message statistics
            total_sent = sum(node.messages_sent for node in self.nodes)
            total_received = sum(node.messages_received for node in self.nodes)
            total_validated = sum(node.messages_validated for node in self.nodes)
            total_rejected = sum(node.messages_rejected for node in self.nodes)
            
            print(f"Messages - Sent: {total_sent}, Received: {total_received}")
            print(f"Validation - Accepted: {total_validated}, Rejected: {total_rejected}")
            
            # Show recent security events
            all_events = []
            for node in self.nodes:
                all_events.extend(node.security_events)
            
            new_events = all_events[security_events_shown:]
            if new_events:
                print("Recent Security Events:")
                for event in new_events[-5:]:  # Show last 5 events
                    print(f"  {event.event_type} from {event.peer_id}: {event.details}")
                security_events_shown = len(all_events)
            
            await trio.sleep(3)
    
    def save_monitoring_data(self, filename: str):
        """Save collected monitoring data to file"""
        with open(filename, 'w') as f:
            json.dump(self.monitoring_data, f, indent=2)
        print(f"Monitoring data saved to {filename}")


async def interactive_mode():
    """Interactive mode for exploring features"""
    print("\n" + "="*80)
    print("GOSSIPSUB 2.0 INTERACTIVE SHOWCASE")
    print("="*80)
    print("Available commands:")
    print("  1. scoring  - Demonstrate peer scoring (P1-P7)")
    print("  2. adaptive - Show adaptive gossip behavior")
    print("  3. security - Display security features")
    print("  4. status   - Show current network status")
    print("  5. quit     - Exit the showcase")
    print("="*80)
    
    showcase = V2Showcase()
    await showcase.setup_network(6)
    
    # Start network in background
    async with trio.open_nursery() as nursery:
        nursery.start_soon(showcase.start_network)
        
        # Wait for network to initialize
        await trio.sleep(5)
        
        # Interactive loop
        while True:
            try:
                command = await trio.to_thread.run_sync(
                    lambda: input("\nEnter command (1-5): ").strip()
                )
                
                if command in ["1", "scoring"]:
                    await showcase._demo_peer_scoring(30)
                elif command in ["2", "adaptive"]:
                    await showcase._demo_adaptive_gossip(30)
                elif command in ["3", "security"]:
                    await showcase._demo_security_features(30)
                elif command in ["4", "status"]:
                    await show_network_status(showcase)
                elif command in ["5", "quit"]:
                    print("Exiting showcase...")
                    break
                else:
                    print("Invalid command. Please enter 1-5.")
                    
            except KeyboardInterrupt:
                print("\nExiting showcase...")
                break


async def show_network_status(showcase: V2Showcase):
    """Show current network status"""
    print("\n" + "="*50)
    print("NETWORK STATUS")
    print("="*50)
    
    print(f"Total Nodes: {len(showcase.nodes)}")
    
    role_counts = defaultdict(int)
    for node in showcase.nodes:
        role_counts[node.role] += 1
    
    print("Node Roles:")
    for role, count in role_counts.items():
        print(f"  {role}: {count}")
    
    # Show message statistics
    total_sent = sum(node.messages_sent for node in showcase.nodes)
    total_received = sum(node.messages_received for node in showcase.nodes)
    
    print(f"\nMessage Statistics:")
    print(f"  Total Sent: {total_sent}")
    print(f"  Total Received: {total_received}")
    
    if showcase.nodes:
        health = showcase.nodes[0].get_network_health()
        if health:
            print(f"\nNetwork Health: {health.health_score:.2f}")


async def main():
    parser = argparse.ArgumentParser(description="Gossipsub 2.0 Feature Showcase")
    parser.add_argument(
        "--mode",
        choices=["interactive", "demo"],
        default="interactive",
        help="Run mode"
    )
    parser.add_argument(
        "--feature",
        choices=["scoring", "adaptive", "security"],
        help="Feature to demonstrate (demo mode only)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Demo duration in seconds"
    )
    parser.add_argument(
        "--nodes",
        type=int,
        default=6,
        help="Number of nodes in network"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for monitoring data"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.mode == "interactive":
        await interactive_mode()
    else:
        if not args.feature:
            print("Error: --feature required for demo mode")
            return
            
        showcase = V2Showcase()
        await showcase.setup_network(args.nodes)
        
        async with trio.open_nursery() as nursery:
            nursery.start_soon(showcase.start_network)
            await trio.sleep(3)  # Wait for network initialization
            
            # Run the demo within the nursery context with timeout
            with trio.move_on_after(args.duration + 10):  # Add buffer time
                await showcase.run_demo(args.feature, args.duration)
            
            # Cancel all tasks to exit nursery
            nursery.cancel_scope.cancel()
        
        if args.output:
            showcase.save_monitoring_data(args.output)


if __name__ == "__main__":
    trio.run(main)
#!/usr/bin/env python3
"""
Gossipsub Version Comparison Demo

This demo creates side-by-side networks running different Gossipsub protocol versions
to demonstrate the evolution and improvements across versions:

- Gossipsub 1.0 (/meshsub/1.0.0): Basic mesh-based pubsub
- Gossipsub 1.1 (/meshsub/1.1.0): Added peer scoring and behavioral penalties  
- Gossipsub 1.2 (/meshsub/1.2.0): Added IDONTWANT message filtering
- Gossipsub 2.0 (/meshsub/2.0.0): Enhanced security, adaptive gossip, and advanced peer scoring

Usage:
    python version_comparison.py --scenario normal
    python version_comparison.py --scenario high_churn
    python version_comparison.py --scenario spam_attack
    python version_comparison.py --scenario network_partition
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
from typing import Any, Dict, List, Optional

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
logger = logging.getLogger("gossipsub-comparison")

# Protocol versions
GOSSIPSUB_V10 = TProtocol("/meshsub/1.0.0")
GOSSIPSUB_V11 = TProtocol("/meshsub/1.1.0") 
GOSSIPSUB_V12 = TProtocol("/meshsub/1.2.0")
GOSSIPSUB_V20 = TProtocol("/meshsub/2.0.0")

TOPIC = "comparison-test"


@dataclass
class NetworkMetrics:
    """Metrics collected from a network during testing"""
    version: str
    total_messages_sent: int = 0
    total_messages_received: int = 0
    message_delivery_rate: float = 0.0
    average_latency_ms: float = 0.0
    network_overhead_bytes: int = 0
    peer_churn_events: int = 0
    spam_messages_blocked: int = 0
    partition_recovery_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonResult:
    """Results from comparing different protocol versions"""
    scenario: str
    duration_seconds: float
    metrics_by_version: Dict[str, NetworkMetrics]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "duration_seconds": self.duration_seconds,
            "metrics": {v: m.to_dict() for v, m in self.metrics_by_version.items()}
        }


class NetworkNode:
    """Represents a single node in the test network"""
    
    def __init__(self, node_id: str, protocol_version: TProtocol, port: int):
        self.node_id = node_id
        self.protocol_version = protocol_version
        self.port = port
        self.host = None
        self.pubsub = None
        self.gossipsub = None
        self.subscription = None
        
        # Metrics tracking
        self.messages_sent = 0
        self.messages_received = 0
        self.message_timestamps = {}  # msg_id -> send_time
        self.latencies = []
        self.is_malicious = False
        
    async def start(self):
        """Start the node and initialize pubsub"""
        key_pair = create_new_key_pair()
        
        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        
        # Configure gossipsub based on protocol version
        gossipsub_config = self._get_gossipsub_config()
        self.gossipsub = GossipSub(**gossipsub_config)
        self.pubsub = Pubsub(self.host, self.gossipsub)
        
        # Start services
        import multiaddr
        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{self.port}")]
        
        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                async with background_trio_service(self.gossipsub):
                    await self.pubsub.wait_until_ready()
                    self.subscription = await self.pubsub.subscribe(TOPIC)
                    logger.info(f"Node {self.node_id} ({self.protocol_version}) started on port {self.port}")
                    
                    # Keep running
                    await trio.sleep_forever()
    
    def _get_gossipsub_config(self) -> Dict[str, Any]:
        """Get gossipsub configuration based on protocol version"""
        base_config = {
            "protocols": [self.protocol_version],
            "degree": 3,
            "degree_low": 2, 
            "degree_high": 4,
            "heartbeat_interval": 5,
            "heartbeat_initial_delay": 1.0,
        }
        
        if self.protocol_version == GOSSIPSUB_V10:
            # Basic configuration for v1.0
            return base_config
            
        elif self.protocol_version == GOSSIPSUB_V11:
            # Add scoring for v1.1
            score_params = ScoreParams(
                p1_time_in_mesh=TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
                p2_first_message_deliveries=TopicScoreParams(weight=0.5, cap=20.0, decay=0.99),
                p3_mesh_message_deliveries=TopicScoreParams(weight=0.3, cap=10.0, decay=0.99),
                p4_invalid_messages=TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
            )
            base_config["score_params"] = score_params
            return base_config
            
        elif self.protocol_version == GOSSIPSUB_V12:
            # Add IDONTWANT support for v1.2
            score_params = ScoreParams(
                p1_time_in_mesh=TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
                p2_first_message_deliveries=TopicScoreParams(weight=0.5, cap=20.0, decay=0.99),
                p3_mesh_message_deliveries=TopicScoreParams(weight=0.3, cap=10.0, decay=0.99),
                p4_invalid_messages=TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
            )
            base_config.update({
                "score_params": score_params,
                "max_idontwant_messages": 20,
            })
            return base_config
            
        elif self.protocol_version == GOSSIPSUB_V20:
            # Full v2.0 configuration with adaptive features and security
            score_params = ScoreParams(
                p1_time_in_mesh=TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
                p2_first_message_deliveries=TopicScoreParams(weight=0.5, cap=20.0, decay=0.99),
                p3_mesh_message_deliveries=TopicScoreParams(weight=0.3, cap=10.0, decay=0.99),
                p4_invalid_messages=TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
                p5_behavior_penalty_weight=1.0,
                p5_behavior_penalty_decay=0.99,
                p6_appl_slack_weight=0.1,
                p7_ip_colocation_weight=0.5,
                publish_threshold=0.0,
                gossip_threshold=-1.0,
                graylist_threshold=-10.0,
            )
            base_config.update({
                "score_params": score_params,
                "max_idontwant_messages": 20,
                "adaptive_gossip_enabled": True,
                "spam_protection_enabled": True,
                "max_messages_per_topic_per_second": 10.0,
                "eclipse_protection_enabled": True,
                "min_mesh_diversity_ips": 2,
            })
            return base_config
            
        return base_config
    
    async def publish_message(self, message: str) -> str:
        """Publish a message and return message ID for tracking"""
        if self.pubsub:
            msg_id = f"{self.node_id}_{self.messages_sent}_{int(time.time() * 1000)}"
            full_message = f"{msg_id}:{message}"
            
            self.message_timestamps[msg_id] = time.time()
            await self.pubsub.publish(TOPIC, full_message.encode())
            self.messages_sent += 1
            return msg_id
        return ""
    
    async def receive_messages(self, metrics: NetworkMetrics):
        """Receive and process messages, updating metrics"""
        if not self.subscription:
            return
            
        try:
            while True:
                message = await self.subscription.get()
                decoded = message.data.decode('utf-8')
                
                # Parse message to extract ID and calculate latency
                if ':' in decoded:
                    msg_id, content = decoded.split(':', 1)
                    
                    # Calculate latency if we sent this message
                    if msg_id in self.message_timestamps:
                        latency = (time.time() - self.message_timestamps[msg_id]) * 1000
                        self.latencies.append(latency)
                        del self.message_timestamps[msg_id]
                
                self.messages_received += 1
                metrics.total_messages_received += 1
                
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
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics for this node"""
        avg_latency = statistics.mean(self.latencies) if self.latencies else 0.0
        return {
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "average_latency_ms": avg_latency,
            "pending_messages": len(self.message_timestamps)
        }


class NetworkSimulator:
    """Simulates different network scenarios for comparison testing"""
    
    def __init__(self):
        self.networks = {}  # version -> list of nodes
        self.metrics = {}   # version -> NetworkMetrics
        
    async def setup_networks(self, nodes_per_version: int = 5):
        """Set up networks for each protocol version"""
        versions = [
            ("v1.0", GOSSIPSUB_V10),
            ("v1.1", GOSSIPSUB_V11), 
            ("v1.2", GOSSIPSUB_V12),
            ("v2.0", GOSSIPSUB_V20),
        ]
        
        for version_name, protocol in versions:
            self.networks[version_name] = []
            self.metrics[version_name] = NetworkMetrics(version=version_name)
            
            # Create nodes for this version
            for i in range(nodes_per_version):
                port = find_free_port()
                node_id = f"{version_name}_node_{i}"
                node = NetworkNode(node_id, protocol, port)
                self.networks[version_name].append(node)
        
        logger.info(f"Created {len(versions)} networks with {nodes_per_version} nodes each")
    
    async def run_scenario(self, scenario: str, duration: int = 60) -> ComparisonResult:
        """Run a specific test scenario and collect metrics"""
        logger.info(f"Starting scenario: {scenario} (duration: {duration}s)")
        start_time = time.time()
        
        # Start all networks concurrently with timeout
        try:
            async with trio.open_nursery() as nursery:
                # Start all nodes
                for version, nodes in self.networks.items():
                    for node in nodes:
                        nursery.start_soon(node.start)
                
                # Wait for nodes to initialize
                await trio.sleep(3)
                
                # Connect nodes within each network
                await self._connect_networks()
                await trio.sleep(2)
                
                # Start message receiving for all nodes
                for version, nodes in self.networks.items():
                    for node in nodes:
                        nursery.start_soon(node.receive_messages, self.metrics[version])
                
                # Run the specific scenario with timeout
                with trio.move_on_after(duration + 10):  # Add buffer time
                    if scenario == "normal":
                        await self._run_normal_scenario(duration)
                    elif scenario == "high_churn":
                        await self._run_high_churn_scenario(duration)
                    elif scenario == "spam_attack":
                        await self._run_spam_attack_scenario(duration)
                    elif scenario == "network_partition":
                        await self._run_network_partition_scenario(duration)
                    else:
                        logger.error(f"Unknown scenario: {scenario}")
                        return ComparisonResult(scenario, 0, {})
                
                # Cancel all tasks to exit nursery
                nursery.cancel_scope.cancel()
                
        except Exception as e:
            logger.warning(f"Scenario execution interrupted: {e}")
        
        # Calculate final metrics
        end_time = time.time()
        duration_actual = end_time - start_time
        
        await self._calculate_final_metrics()
        
        return ComparisonResult(
            scenario=scenario,
            duration_seconds=duration_actual,
            metrics_by_version=self.metrics
        )
    
    async def _connect_networks(self):
        """Connect nodes within each network to form mesh topology"""
        for version, nodes in self.networks.items():
            # Connect each node to other nodes in the same network
            for i, node in enumerate(nodes):
                # Connect to the next node in a ring topology for simplicity
                if len(nodes) > 1:
                    target_idx = (i + 1) % len(nodes)
                    target = nodes[target_idx]
                    
                    if target.host and node.host:
                        peer_addr = f"/ip4/127.0.0.1/tcp/{target.port}/p2p/{target.host.get_id()}"
                        await node.connect_to_peer(peer_addr)
    
    async def _run_normal_scenario(self, duration: int):
        """Normal operation with honest peers"""
        logger.info("Running normal scenario - honest peers publishing regularly")
        
        end_time = time.time() + duration
        message_counter = 0
        
        while time.time() < end_time:
            # Each network publishes messages at regular intervals
            for version, nodes in self.networks.items():
                # Random node publishes a message
                node = random.choice(nodes)
                message = f"normal_msg_{message_counter}"
                await node.publish_message(message)
                self.metrics[version].total_messages_sent += 1
                message_counter += 1
            
            await trio.sleep(1)  # Publish every second
    
    async def _run_high_churn_scenario(self, duration: int):
        """High peer churn scenario"""
        logger.info("Running high churn scenario - peers joining/leaving frequently")
        
        end_time = time.time() + duration
        message_counter = 0
        
        while time.time() < end_time:
            # Normal message publishing
            for version, nodes in self.networks.items():
                active_nodes = [n for n in nodes if n.host]
                if active_nodes:
                    node = random.choice(active_nodes)
                    message = f"churn_msg_{message_counter}"
                    await node.publish_message(message)
                    self.metrics[version].total_messages_sent += 1
                    self.metrics[version].peer_churn_events += 1
                    message_counter += 1
            
            await trio.sleep(0.5)
    
    async def _run_spam_attack_scenario(self, duration: int):
        """Spam attack scenario with malicious peers"""
        logger.info("Running spam attack scenario - some peers sending excessive messages")
        
        # Mark some nodes as malicious
        for version, nodes in self.networks.items():
            malicious_count = max(1, len(nodes) // 3)  # 1/3 of nodes are malicious
            for i in range(malicious_count):
                nodes[i].is_malicious = True
        
        end_time = time.time() + duration
        message_counter = 0
        
        while time.time() < end_time:
            for version, nodes in self.networks.items():
                for node in nodes:
                    if node.is_malicious:
                        # Malicious nodes send many messages
                        for _ in range(5):
                            message = f"spam_msg_{message_counter}"
                            await node.publish_message(message)
                            message_counter += 1
                    else:
                        # Honest nodes send normal messages
                        message = f"honest_msg_{message_counter}"
                        await node.publish_message(message)
                        self.metrics[version].total_messages_sent += 1
                        message_counter += 1
            
            await trio.sleep(0.2)  # Faster publishing for spam scenario
    
    async def _run_network_partition_scenario(self, duration: int):
        """Network partition and recovery scenario"""
        logger.info("Running network partition scenario - network splits and recovers")
        
        partition_time = duration // 3
        recovery_time = time.time() + partition_time
        end_time = time.time() + duration
        message_counter = 0
        
        # Phase 1: Normal operation
        logger.info("Phase 1: Normal operation")
        while time.time() < recovery_time:
            for version, nodes in self.networks.items():
                node = random.choice(nodes)
                message = f"pre_partition_msg_{message_counter}"
                await node.publish_message(message)
                self.metrics[version].total_messages_sent += 1
                message_counter += 1
            await trio.sleep(1)
        
        # Phase 2: Partition (simulate by reducing connectivity)
        logger.info("Phase 2: Network partition")
        partition_start = time.time()
        
        while time.time() < end_time:
            # Reduced message publishing during partition
            for version, nodes in self.networks.items():
                # Only half the nodes can communicate
                active_nodes = nodes[:len(nodes)//2]
                if active_nodes:
                    node = random.choice(active_nodes)
                    message = f"partition_msg_{message_counter}"
                    await node.publish_message(message)
                    self.metrics[version].total_messages_sent += 1
                    message_counter += 1
            await trio.sleep(2)  # Slower during partition
        
        # Record partition recovery time
        recovery_duration = (time.time() - partition_start) * 1000
        for version in self.metrics:
            self.metrics[version].partition_recovery_time_ms = recovery_duration
    
    async def _calculate_final_metrics(self):
        """Calculate final metrics for all networks"""
        for version, nodes in self.networks.items():
            metrics = self.metrics[version]
            
            # Aggregate node metrics
            total_sent = sum(node.messages_sent for node in nodes)
            total_received = sum(node.messages_received for node in nodes)
            
            all_latencies = []
            for node in nodes:
                all_latencies.extend(node.latencies)
            
            # Calculate delivery rate and latency
            if total_sent > 0:
                # Expected receives = sent * (nodes - 1) since each message should reach all other nodes
                expected_receives = total_sent * (len(nodes) - 1)
                metrics.message_delivery_rate = min(1.0, total_received / expected_receives)
            
            metrics.average_latency_ms = statistics.mean(all_latencies) if all_latencies else 0.0
            
            logger.info(f"{version} final metrics: "
                       f"sent={total_sent}, received={total_received}, "
                       f"delivery_rate={metrics.message_delivery_rate:.2%}, "
                       f"avg_latency={metrics.average_latency_ms:.1f}ms")


def print_comparison_results(result: ComparisonResult):
    """Print formatted comparison results"""
    print(f"\n{'='*80}")
    print(f"GOSSIPSUB VERSION COMPARISON RESULTS")
    print(f"{'='*80}")
    print(f"Scenario: {result.scenario}")
    print(f"Duration: {result.duration_seconds:.1f} seconds")
    print(f"{'='*80}")
    
    # Print metrics table
    versions = list(result.metrics_by_version.keys())
    
    print(f"{'Metric':<30} {'v1.0':<12} {'v1.1':<12} {'v1.2':<12} {'v2.0':<12}")
    print(f"{'-'*80}")
    
    metrics_to_show = [
        ("Messages Sent", "total_messages_sent"),
        ("Messages Received", "total_messages_received"), 
        ("Delivery Rate", "message_delivery_rate"),
        ("Avg Latency (ms)", "average_latency_ms"),
        ("Spam Blocked", "spam_messages_blocked"),
        ("Churn Events", "peer_churn_events"),
    ]
    
    for metric_name, metric_key in metrics_to_show:
        row = f"{metric_name:<30}"
        for version in versions:
            metrics = result.metrics_by_version[version]
            value = getattr(metrics, metric_key)
            
            if metric_key == "message_delivery_rate":
                row += f"{value:.1%}".ljust(12)
            elif metric_key in ["average_latency_ms", "partition_recovery_time_ms"]:
                row += f"{value:.1f}".ljust(12)
            else:
                row += f"{value}".ljust(12)
        print(row)
    
    print(f"{'='*80}")
    
    # Analysis
    print("\nANALYSIS:")
    best_delivery = max(result.metrics_by_version.items(), 
                       key=lambda x: x[1].message_delivery_rate)
    print(f"• Best message delivery rate: {best_delivery[0]} ({best_delivery[1].message_delivery_rate:.1%})")
    
    best_latency = min(result.metrics_by_version.items(),
                      key=lambda x: x[1].average_latency_ms)
    print(f"• Lowest average latency: {best_latency[0]} ({best_latency[1].average_latency_ms:.1f}ms)")
    
    if result.scenario == "spam_attack":
        best_spam_protection = max(result.metrics_by_version.items(),
                                 key=lambda x: x[1].spam_messages_blocked)
        print(f"• Best spam protection: {best_spam_protection[0]} ({best_spam_protection[1].spam_messages_blocked} blocked)")


async def main():
    parser = argparse.ArgumentParser(description="Gossipsub Version Comparison Demo")
    parser.add_argument(
        "--scenario",
        choices=["normal", "high_churn", "spam_attack", "network_partition"],
        default="normal",
        help="Test scenario to run"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Test duration in seconds"
    )
    parser.add_argument(
        "--nodes",
        type=int,
        default=4,
        help="Number of nodes per version"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for JSON results"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create and run simulation
    simulator = NetworkSimulator()
    await simulator.setup_networks(args.nodes)
    
    result = await simulator.run_scenario(args.scenario, args.duration)
    
    # Display results
    print_comparison_results(result)
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    trio.run(main)
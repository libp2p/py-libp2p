#!/usr/bin/env python3
"""
Gossipsub 2.0 Example

This example demonstrates Gossipsub 2.0 protocol (/meshsub/2.0.0).
Gossipsub 2.0 adds enhanced security, adaptive gossip, and advanced peer scoring
to provide the most robust and efficient pubsub protocol.

Features demonstrated:
- All Gossipsub 1.2 features (peer scoring, IDONTWANT)
- Enhanced peer scoring with P6 (application-specific) and P7 (IP colocation)
- Adaptive gossip behavior based on network health
- Advanced security features:
  - Spam protection with rate limiting
  - Eclipse attack protection via IP diversity
  - Equivocation detection
  - Enhanced message validation

Usage:
    python gossipsub_v2.0.py --nodes 5 --duration 30
"""

import argparse
import logging
import random
import time

import trio

from libp2p import new_host
from libp2p.abc import IHost, ISubscriptionAPI
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
logger = logging.getLogger("gossipsub-v2.0")

# Protocol version
GOSSIPSUB_V20 = TProtocol("/meshsub/2.0.0")
TOPIC = "gossipsub-v2.0-demo"


class GossipsubV20Node:
    """A node running Gossipsub 2.0"""

    def __init__(self, node_id: str, port: int, role: str = "honest"):
        self.node_id = node_id
        self.port = port
        self.role = role  # "honest", "spammer", "validator"
        self.host: IHost | None = None
        self.pubsub: Pubsub | None = None
        self.gossipsub: GossipSub | None = None
        self.subscription: ISubscriptionAPI | None = None
        self.messages_sent = 0
        self.messages_received = 0
        self.messages_validated = 0
        self.messages_rejected = 0

    async def start(self):
        """Start the node with Gossipsub 2.0 configuration"""
        key_pair = create_new_key_pair()

        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )

        # Configure Gossipsub 2.0 - full feature set
        score_params = ScoreParams(
            # Topic-scoped parameters (P1-P4)
            p1_time_in_mesh=TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
            p2_first_message_deliveries=TopicScoreParams(
                weight=0.5, cap=20.0, decay=0.99
            ),
            p3_mesh_message_deliveries=TopicScoreParams(
                weight=0.3, cap=10.0, decay=0.99
            ),
            p4_invalid_messages=TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
            # Global behavioral penalty (P5)
            p5_behavior_penalty_weight=1.0,
            p5_behavior_penalty_decay=0.99,
            # Application-specific score (P6)
            p6_appl_slack_weight=0.1,
            p6_appl_slack_decay=0.99,
            # IP colocation penalty (P7)
            p7_ip_colocation_weight=0.5,
            p7_ip_colocation_threshold=3,
            # Application-specific scoring function
            app_specific_score_fn=self._application_score_function,
        )

        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_V20],
            degree=4,
            degree_low=2,
            degree_high=6,
            heartbeat_interval=5,
            heartbeat_initial_delay=1.0,
            score_params=score_params,
            # v1.2 feature: IDONTWANT support
            max_idontwant_messages=20,
            # v2.0 adaptive features
            adaptive_gossip_enabled=True,
            # v2.0 security features
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
                    logger.info(
                        f"Node {self.node_id} (Gossipsub 2.0, {self.role}) started on "
                        f"port {self.port}"
                    )

                    # Keep running
                    await trio.sleep_forever()

    def _application_score_function(self, peer_id: ID) -> float:
        """Custom application scoring function (P6)"""
        # Example: Reward peers that have been connected longer
        # In a real application, this could be based on stake, reputation, etc.
        if self.gossipsub and peer_id in getattr(self.gossipsub, "peers", {}):
            # Simple time-based scoring for demo
            return min(5.0, time.time() % 10)  # Varies over time for demo
        return 0.0

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
                if self.subscription is None:
                    break
                message = await self.subscription.get()
                decoded = message.data.decode("utf-8")
                self.messages_received += 1

                # Simulate message validation
                if self._validate_message(message):
                    self.messages_validated += 1
                    logger.info(f"Node {self.node_id} received (valid): {decoded}")
                else:
                    self.messages_rejected += 1
                    logger.warning(f"Node {self.node_id} received (invalid): {decoded}")
        except Exception as e:
            logger.debug(f"Node {self.node_id} receive loop ended: {e}")

    def _validate_message(self, message) -> bool:
        """Simple message validation"""
        try:
            decoded = message.data.decode("utf-8")
            # Basic validation: message should have expected format
            return "_msg_" in decoded and len(decoded) < 1000
        except Exception:
            return False

    async def connect_to_peer(self, peer_addr: str):
        """Connect to another peer"""
        if self.host:
            try:
                import multiaddr

                from libp2p.peer.peerinfo import info_from_p2p_addr

                maddr = multiaddr.Multiaddr(peer_addr)
                info = info_from_p2p_addr(maddr)
                await self.host.connect(info)
                logger.debug(f"Node {self.node_id} connected to {peer_addr}")
            except Exception as e:
                logger.debug(
                    f"Node {self.node_id} failed to connect to {peer_addr}: {e}"
                )


class GossipsubV20Demo:
    """Demo controller for Gossipsub 2.0"""

    def __init__(self):
        self.nodes: list[GossipsubV20Node] = []

    async def setup_network(self, node_count: int = 5):
        """Set up a network of nodes with different roles"""
        # Mix of honest, spammer, and validator nodes
        roles = ["honest"] * (node_count - 2) + ["spammer"] * 1 + ["validator"] * 1

        for i in range(node_count):
            port = find_free_port()
            role = roles[i] if i < len(roles) else "honest"
            node = GossipsubV20Node(f"node_{i}", port, role)
            self.nodes.append(node)

        logger.info(f"Created network with {node_count} nodes running Gossipsub 2.0")

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

                print(f"\n{'=' * 60}")
                print("GOSSIPSUB 2.0 DEMO")
                print(f"{'=' * 60}")
                print(f"Running for {duration} seconds...")
                print("Protocol: /meshsub/2.0.0")
                print("Features: Adaptive gossip, advanced security, P6/P7 scoring")
                print(f"{'=' * 60}\n")

                while time.time() < end_time:
                    # Honest nodes publish normally
                    honest_nodes = [n for n in self.nodes if n.role == "honest"]
                    if honest_nodes:
                        node = random.choice(honest_nodes)
                        message = f"honest_msg_{message_counter}_{int(time.time())}"
                        await node.publish_message(message)
                        message_counter += 1

                    # Validator nodes publish less frequently but with high quality
                    validator_nodes = [n for n in self.nodes if n.role == "validator"]
                    if validator_nodes and random.random() < 0.3:  # 30% chance
                        node = validator_nodes[0]
                        message = f"validator_msg_{message_counter}_{int(time.time())}"
                        await node.publish_message(message)
                        message_counter += 1

                    # Spammer nodes try to send many messages (will be rate-limited)
                    spammer_nodes = [n for n in self.nodes if n.role == "spammer"]
                    if spammer_nodes and random.random() < 0.5:  # 50% chance
                        node = spammer_nodes[0]
                        # Try to send multiple messages quickly
                        for _ in range(3):
                            message = f"spam_msg_{message_counter}_{int(time.time())}"
                            await node.publish_message(message)
                            message_counter += 1
                            await trio.sleep(0.1)  # Small delay between spam messages

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
                    peer_addr = (
                        f"/ip4/127.0.0.1/tcp/{target.port}/p2p/{target.host.get_id()}"
                    )
                    await node.connect_to_peer(peer_addr)

                # Also connect to one more node for better connectivity
                if len(self.nodes) > 2:
                    target_idx2 = (i + 2) % len(self.nodes)
                    target2 = self.nodes[target_idx2]

                    if target2.host and node.host:
                        peer_addr2 = (
                            f"/ip4/127.0.0.1/tcp/{target2.port}/p2p/"
                            f"{target2.host.get_id()}"
                        )
                        await node.connect_to_peer(peer_addr2)

    def _print_statistics(self):
        """Print demo statistics"""
        print(f"\n{'=' * 60}")
        print("DEMO STATISTICS")
        print(f"{'=' * 60}")

        total_sent = sum(node.messages_sent for node in self.nodes)
        total_received = sum(node.messages_received for node in self.nodes)
        total_validated = sum(node.messages_validated for node in self.nodes)
        total_rejected = sum(node.messages_rejected for node in self.nodes)

        honest_sent = sum(n.messages_sent for n in self.nodes if n.role == "honest")
        spammer_sent = sum(n.messages_sent for n in self.nodes if n.role == "spammer")
        validator_sent = sum(
            n.messages_sent for n in self.nodes if n.role == "validator"
        )

        print(f"Total messages sent: {total_sent}")
        print(f"  Honest nodes: {honest_sent}")
        print(f"  Spammer nodes: {spammer_sent}")
        print(f"  Validator nodes: {validator_sent}")
        print(f"Total messages received: {total_received}")
        print(f"Messages validated: {total_validated}")
        print(f"Messages rejected: {total_rejected}")
        print("\nPer-node statistics:")
        for node in self.nodes:
            print(
                f"  {node.node_id} ({node.role}): "
                f"sent={node.messages_sent}, received={node.messages_received}, "
                f"validated={node.messages_validated}, "
                f"rejected={node.messages_rejected}"
            )

        print(f"\n{'=' * 60}")
        print("Gossipsub 2.0 Features:")
        print("  ✓ All Gossipsub 1.2 features")
        print("  ✓ Enhanced peer scoring:")
        print("    - P6: Application-specific score")
        print("    - P7: IP colocation penalty")
        print("  ✓ Adaptive gossip behavior")
        print("  ✓ Advanced security features:")
        print("    - Spam protection with rate limiting")
        print("    - Eclipse attack protection")
        print("    - Equivocation detection")
        print("    - Enhanced message validation")
        print(f"{'=' * 60}\n")


async def main():
    parser = argparse.ArgumentParser(description="Gossipsub 2.0 Example")
    parser.add_argument(
        "--nodes", type=int, default=5, help="Number of nodes in the network"
    )
    parser.add_argument(
        "--duration", type=int, default=30, help="Demo duration in seconds"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    demo = GossipsubV20Demo()
    await demo.setup_network(args.nodes)
    await demo.start_network(args.duration)


if __name__ == "__main__":
    trio.run(main)

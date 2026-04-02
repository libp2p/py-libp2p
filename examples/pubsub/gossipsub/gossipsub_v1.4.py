#!/usr/bin/env python3
"""
GossipSub 1.4 Example

This example demonstrates GossipSub v1.4 protocol (/meshsub/1.4.0).
GossipSub 1.4 focuses on enhanced rate limiting, GRAFT flood protection,
and adaptive gossip parameter tuning based on network health metrics.

Features demonstrated:
- All GossipSub 1.3 features (Extensions Control Message, Topic Observation)
- IWANT request rate limiting per peer (anti-spam)
- IHAVE message rate limiting per peer per topic (anti-spam)
- GRAFT flood protection with automatic score penalty
- Adaptive gossip factor based on network health score
- Opportunistic grafting threshold adaptation
- Heartbeat interval adaptation under poor network conditions
- Extended scoring (P5-P7) with v1.4 protocol gating

Node roles in this demo:
  - honest     : publishes and receives messages normally
  - spammer    : sends rapid IWANT / IHAVE style spam to trigger rate limits
  - observer   : uses Topic Observation (IHAVE-only) inherited from v1.3
  - validator  : receives messages and validates them; no publishing

Usage:
    python gossipsub_v1.4.py --nodes 6 --duration 40
    python gossipsub_v1.4.py --nodes 6 --duration 40 --verbose
"""

import argparse
import logging
import random
import time

import trio

from libp2p import new_host
from libp2p.abc import IHost, ISubscriptionAPI
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.pubsub.extensions import PeerExtensions
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V14, GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.anyio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("gossipsub-v1.4")

TOPIC = "gossipsub-v1.4-demo"


class GossipsubV14Node:
    """
    A node running GossipSub v1.4.

    Roles:
      - "honest"    – subscribes and publishes messages at a normal rate
      - "spammer"   – sends messages rapidly to exercise rate limiting
      - "observer"  – uses Topic Observation (inherited from v1.3)
      - "validator" – subscribes and receives messages, no publishing
    """

    def __init__(self, node_id: str, port: int, role: str = "honest"):
        self.node_id = node_id
        self.port = port
        self.role = role

        self.host: IHost | None = None
        self.pubsub: Pubsub | None = None
        self.gossipsub: GossipSub | None = None
        self.subscription: ISubscriptionAPI | None = None

        self.messages_sent = 0
        self.messages_received = 0
        self.rate_limit_hits = 0

    async def start(self) -> None:
        """Initialise the libp2p host and GossipSub v1.4 router."""
        import multiaddr

        key_pair = create_new_key_pair()

        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )

        # Full peer scoring: P1-P4 topic-scoped + P5 behavior + P6/P7 global.
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
            p2_first_message_deliveries=TopicScoreParams(
                weight=0.5, cap=20.0, decay=0.99
            ),
            p3_mesh_message_deliveries=TopicScoreParams(
                weight=0.3, cap=10.0, decay=0.99
            ),
            p4_invalid_messages=TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
            p5_behavior_penalty_weight=1.0,
            p5_behavior_penalty_decay=0.99,
        )

        # Advertise v1.3-compatible extensions (Topic Observation + test extension).
        my_extensions = PeerExtensions(
            topic_observation=True,
            test_extension=True,
        )

        # v1.4-specific constructor parameters:
        #   max_iwant_requests_per_second  – caps IWANT storm per peer
        #   max_ihave_messages_per_second  – caps IHAVE flood per peer/topic
        #   graft_flood_threshold          – minimum seconds between PRUNE and GRAFT
        #   adaptive_gossip_enabled        – turn on health-based parameter adaptation
        self.gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V14],
            degree=3,
            degree_low=2,
            degree_high=4,
            heartbeat_interval=5,
            heartbeat_initial_delay=1.0,
            score_params=score_params,
            max_idontwant_messages=20,
            my_extensions=my_extensions,
            # v1.4 rate limiting
            adaptive_gossip_enabled=True,
        )

        # Override v1.4 rate limiting thresholds directly on the router so the
        # demo can observe them being triggered with a small message volume.
        self.gossipsub.max_iwant_requests_per_second = 5.0
        self.gossipsub.max_ihave_messages_per_second = 5.0
        self.gossipsub.graft_flood_threshold = 8.0

        self.pubsub = Pubsub(self.host, self.gossipsub)

        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{self.port}")]

        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                async with background_trio_service(self.gossipsub):
                    await self.pubsub.wait_until_ready()

                    # observers use Topic Observation – no full subscription needed.
                    if self.role in ("honest", "spammer", "validator"):
                        self.subscription = await self.pubsub.subscribe(TOPIC)
                        logger.info(
                            "[%s] subscribed to topic '%s' role=%s",
                            self.node_id,
                            TOPIC,
                            self.role,
                        )

                    logger.info(
                        "Node %s started | role=%s | port=%d | protocol=%s",
                        self.node_id,
                        self.role,
                        self.port,
                        PROTOCOL_ID_V14,
                    )
                    await trio.sleep_forever()

    async def publish_message(self, message: str) -> None:
        """Publish a message to TOPIC."""
        if self.pubsub and self.role in ("honest", "spammer"):
            await self.pubsub.publish(TOPIC, message.encode())
            self.messages_sent += 1
            logger.info(
                "[PUBLISH] node=%s role=%s payload=%s",
                self.node_id,
                self.role,
                message,
            )

    async def receive_messages(self) -> None:
        """Drain the subscription queue and count deliveries."""
        if not self.subscription:
            return
        try:
            while True:
                message = await self.subscription.get()
                decoded = message.data.decode("utf-8")
                self.messages_received += 1
                logger.info(
                    "[RECEIVE] node=%s role=%s payload=%s",
                    self.node_id,
                    self.role,
                    decoded,
                )
        except Exception as exc:
            logger.debug("Node %s receive loop ended: %s", self.node_id, exc)

    async def start_observing(self) -> None:
        """Start Topic Observation (observer role – inherited from v1.3)."""
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.start_observing_topic(TOPIC)
            logger.info(
                "[OBSERVE-START] node=%s topic=%s",
                self.node_id,
                TOPIC,
            )

    async def stop_observing(self) -> None:
        """Stop Topic Observation (observer role)."""
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.stop_observing_topic(TOPIC)
            logger.info(
                "[OBSERVE-STOP] node=%s topic=%s",
                self.node_id,
                TOPIC,
            )

    async def connect_to_peer(self, peer_addr: str) -> None:
        """Connect to a remote peer by multiaddr."""
        if not self.host:
            return
        try:
            import multiaddr

            from libp2p.peer.peerinfo import info_from_p2p_addr

            maddr = multiaddr.Multiaddr(peer_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
            logger.info("[CONNECT] %s -> %s", self.node_id, peer_addr)
        except Exception as exc:
            logger.debug(
                "Node %s failed to connect to %s: %s",
                self.node_id,
                peer_addr,
                exc,
            )

    def v14_status(self) -> str:
        """Return a one-line v1.4 feature status string for this node."""
        if not self.gossipsub:
            return "not started"
        gs = self.gossipsub
        return (
            f"health={gs.network_health_score:.2f} "
            f"gossip_factor={gs.gossip_factor:.2f} "
            f"iwant_limit={gs.max_iwant_requests_per_second:.0f}/s "
            f"ihave_limit={gs.max_ihave_messages_per_second:.0f}/s "
            f"graft_flood_threshold={gs.graft_flood_threshold:.0f}s "
            f"opp_graft_threshold={gs.opportunistic_graft_threshold:.2f}"
        )


class GossipsubV14Demo:
    """
    Demo controller: sets up a mixed-role network and runs a scenario that
    exercises all GossipSub v1.4 features.

    Network layout (default --nodes 6):
      nodes 0-1 → honest
      nodes 2-3 → validator
      nodes 4   → spammer
      nodes 5   → observer
    """

    def __init__(self) -> None:
        self.nodes: list[GossipsubV14Node] = []

    async def setup_network(self, node_count: int = 6) -> None:
        """Allocate ports and create nodes with appropriate roles."""
        roles = _assign_roles(node_count)
        for i in range(node_count):
            port = find_free_port()
            node = GossipsubV14Node(f"node_{i}", port, roles[i])
            self.nodes.append(node)

        role_counts = {r: roles.count(r) for r in set(roles)}
        logger.info(
            "Created %d-node GossipSub v1.4 network: %s",
            node_count,
            role_counts,
        )
        for node in self.nodes:
            logger.info(
                "[PLAN] node=%s role=%s listen=/ip4/127.0.0.1/tcp/%d",
                node.node_id,
                node.role,
                node.port,
            )

    async def start_network(self, duration: int = 40) -> None:
        """Boot all nodes, wire topology, then run the demo loop."""
        try:
            async with trio.open_nursery() as nursery:
                # Boot every node concurrently.
                for node in self.nodes:
                    nursery.start_soon(node.start)

                # Wait for all listening ports to bind.
                await trio.sleep(3)
                logger.info("[STAGE] all node services started")

                # Ring + chord topology (≥2 peers per node).
                logger.info("[STAGE] wiring peer connections (ring + skip links)")
                await self._connect_nodes()
                await trio.sleep(2)
                logger.info("[STAGE] peer wiring complete")
                self._log_v14_snapshot("after-connect")

                # Start receive loops for subscribing roles.
                for node in self.nodes:
                    if node.role in ("honest", "validator", "spammer"):
                        nursery.start_soon(node.receive_messages)
                logger.info("[STAGE] receive loops started")

                # Observer nodes activate Topic Observation after wiring.
                for node in self.nodes:
                    if node.role == "observer":
                        await node.start_observing()

                _print_banner(duration)

                end_time = time.time() + duration
                msg_counter = 0
                tick = 0
                half_time = duration // 2
                spam_burst_done = False
                unobserve_done = False

                while time.time() < end_time:
                    elapsed = duration - (end_time - time.time())

                    # ── Honest nodes publish at a normal cadence ──────────────
                    honest_nodes = [n for n in self.nodes if n.role == "honest"]
                    if honest_nodes:
                        sender = random.choice(honest_nodes)
                        msg = f"msg_{msg_counter}_{int(time.time())}"
                        await sender.publish_message(msg)
                        msg_counter += 1

                    # ── Spammer: burst of rapid messages at the 1/4 mark ─────
                    # This exercises the IWANT / IHAVE rate limiting paths.
                    if elapsed >= duration // 4 and not spam_burst_done:
                        spammers = [n for n in self.nodes if n.role == "spammer"]
                        if spammers:
                            logger.info(
                                "[STAGE] triggering spammer burst (rate-limit demo)"
                            )
                            for _ in range(12):
                                for spammer in spammers:
                                    burst_msg = f"spam_{msg_counter}_{int(time.time())}"
                                    await spammer.publish_message(burst_msg)
                                    msg_counter += 1
                                await trio.sleep(0.05)
                        spam_burst_done = True
                        logger.info(
                            "[STAGE] spammer burst complete – "
                            "check logs for rate-limit warnings"
                        )

                    # ── Midpoint: stop one observer (UNOBSERVE demo) ──────────
                    if elapsed >= half_time and not unobserve_done:
                        for node in self.nodes:
                            if (
                                node.role == "observer"
                                and node.gossipsub is not None
                                and node.gossipsub.topic_observation.is_observing(TOPIC)
                            ):
                                await node.stop_observing()
                                logger.info(
                                    "[STAGE] midpoint UNOBSERVE sent by %s",
                                    node.node_id,
                                )
                                unobserve_done = True
                                break

                    tick += 1
                    self._log_runtime_snapshot(tick, elapsed)
                    await trio.sleep(2)

                await trio.sleep(1)
                self._log_v14_snapshot("final")
                self._print_statistics()
                nursery.cancel_scope.cancel()

        except Exception as exc:
            logger.warning("Demo interrupted: %s", exc)

    async def _connect_nodes(self) -> None:
        """Connect nodes in a ring + one-hop-skip topology."""
        n = len(self.nodes)
        for i, node in enumerate(self.nodes):
            for offset in (1, 2):
                target = self.nodes[(i + offset) % n]
                if target.host and node.host:
                    peer_addr = (
                        f"/ip4/127.0.0.1/tcp/{target.port}/p2p/{target.host.get_id()}"
                    )
                    await node.connect_to_peer(peer_addr)
        logger.info("[STAGE] requested all topology connections")

    def _log_runtime_snapshot(self, tick: int, elapsed: float) -> None:
        honest = [n for n in self.nodes if n.role == "honest"]
        validators = [n for n in self.nodes if n.role == "validator"]
        spammers = [n for n in self.nodes if n.role == "spammer"]
        observers = [n for n in self.nodes if n.role == "observer"]

        published = sum(n.messages_sent for n in honest + spammers)
        delivered = sum(n.messages_received for n in honest + validators)
        active_observers = sum(
            1
            for n in observers
            if n.gossipsub is not None
            and n.gossipsub.topic_observation.is_observing(TOPIC)
        )
        logger.info(
            "[SNAPSHOT t+%ds #%d] published=%d delivered=%d observers=%d/%d",
            int(elapsed),
            tick,
            published,
            delivered,
            active_observers,
            len(observers),
        )

    def _log_v14_snapshot(self, label: str) -> None:
        """Log v1.4 specific metrics for every node."""
        for node in self.nodes:
            if node.gossipsub is None:
                continue
            gs = node.gossipsub
            peers_total = len(gs.peer_protocol)
            v14_peers = sum(
                1
                for pid in gs.peer_protocol
                if gs.supports_protocol_feature(pid, "adaptive_gossip")
            )
            logger.info(
                "[V14-SNAPSHOT:%s] node=%s peers=%d v14=%d %s",
                label,
                node.node_id,
                peers_total,
                v14_peers,
                node.v14_status(),
            )

    def _print_statistics(self) -> None:
        """Print a summary table at the end of the demo."""
        print(f"\n{'=' * 70}")
        print("DEMO STATISTICS")
        print(f"{'=' * 70}")

        total_sent = sum(n.messages_sent for n in self.nodes)
        total_received = sum(n.messages_received for n in self.nodes)

        print(f"Total messages published : {total_sent}")
        print(f"Total messages received  : {total_received}")
        print()
        print(f"{'Node':<10} {'Role':<12} {'Sent':>6} {'Recv':>6}  v1.4 Status")
        print(f"{'-' * 70}")
        for node in self.nodes:
            print(
                f"{node.node_id:<10} {node.role:<12} "
                f"{node.messages_sent:>6} {node.messages_received:>6}  "
                f"{node.v14_status()}"
            )

        print(f"\n{'=' * 70}")
        print("GossipSub 1.4 Features demonstrated:")
        print("  + IWANT request rate limiting per peer (anti-spam)")
        print("  + IHAVE message rate limiting per peer per topic (anti-spam)")
        print("  + GRAFT flood protection with automatic score penalty")
        print("  + Adaptive gossip factor based on network health score")
        print("  + Opportunistic grafting threshold adaptation")
        print("  + Heartbeat interval adaptation under poor network conditions")
        print("  + Extended scoring (P5-P7) gated to /meshsub/1.4.0")
        print("  + Topic Observation (inherited from v1.3) with UNOBSERVE demo")
        print("  + All GossipSub 1.3 features (Extensions Control Message, etc.)")
        print(f"{'=' * 70}\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assign_roles(node_count: int) -> list[str]:
    """
    Distribute roles across nodes.

    With 6 nodes: 2 honest / 2 validator / 1 spammer / 1 observer.
    Smaller counts fall back gracefully.
    """
    if node_count < 2:
        return ["honest"] * node_count
    if node_count == 2:
        return ["honest", "validator"]
    if node_count == 3:
        return ["honest", "validator", "spammer"]

    honest = max(1, node_count // 3)
    spammer = max(1, node_count // 6)
    observer = max(1, node_count // 6)
    validator = node_count - honest - spammer - observer
    return (
        ["honest"] * honest
        + ["validator"] * validator
        + ["spammer"] * spammer
        + ["observer"] * observer
    )


def _print_banner(duration: int) -> None:
    print(f"\n{'=' * 70}")
    print("GOSSIPSUB 1.4 DEMO")
    print(f"{'=' * 70}")
    print("Protocol  : /meshsub/1.4.0")
    print(f"Duration  : {duration} seconds")
    print("Features  : IWANT/IHAVE rate limiting, GRAFT flood protection,")
    print("            adaptive gossip factor, heartbeat adaptation,")
    print("            opportunistic grafting threshold, extended scoring (P5-P7),")
    print("            Topic Observation (inherited from v1.3)")
    print()
    print("Roles:")
    print("  honest    – subscribes + publishes at a normal cadence")
    print("  validator – subscribes, reads messages, no publishing")
    print("  spammer   – bursts messages to trigger rate-limit paths")
    print("  observer  – Topic Observation only (no full subscription)")
    print()
    print(f"  At t={duration // 4}s : spammer burst  (IWANT/IHAVE rate-limit demo)")
    print(f"  At t={duration // 2}s : UNOBSERVE sent by one observer")
    print(f"{'=' * 70}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="GossipSub 1.4 Example")
    parser.add_argument(
        "--nodes", type=int, default=6, help="Total number of nodes (default: 6)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=40,
        help="Demo duration in seconds (default: 40)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    demo = GossipsubV14Demo()
    await demo.setup_network(args.nodes)
    await demo.start_network(args.duration)


if __name__ == "__main__":
    trio.run(main)

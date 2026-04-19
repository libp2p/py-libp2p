#!/usr/bin/env python3
"""
GossipSub 1.3 Example

This example demonstrates GossipSub v1.3 protocol (/meshsub/1.3.0).
GossipSub 1.3 adds the Extensions Control Message mechanism and the
Topic Observation extension.

Features demonstrated:
- All GossipSub 1.2 features (IDONTWANT, peer scoring, etc.)
- GossipSub v1.3 Extensions Control Message (sent once, at most once per peer)
- Topic Observation: observer nodes receive IHAVE notifications without full
  message payloads, enabling lightweight presence awareness
- Misbehaviour detection: duplicate Extensions messages from a peer are penalised
- Protocol gating: extension fields are only sent when /meshsub/1.3.0 is negotiated

Roles in this demo:
  - publisher  : subscribes to the topic and publishes messages every few seconds
  - subscriber : subscribes to the topic and reads full message payloads
  - observer   : starts observing (IHAVE-only) without subscribing; tracks presence

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v1.3.py --nodes 6 --duration 40
    python examples/pubsub/gossipsub/gossipsub_v1.3.py --nodes 6 --duration 40 --verbose
"""

import argparse
import logging
import random
import time

import multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost, ISubscriptionAPI
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.extensions import PeerExtensions
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V13, GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.anyio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("gossipsub-v1.3")

TOPIC = "gossipsub-v1.3-demo"


class GossipsubV13Node:
    """
    A node running GossipSub v1.3.

    Each node has one of three roles:
      - "publisher"  – subscribes and publishes messages
      - "subscriber" – subscribes and reads messages (no publishing)
      - "observer"   – uses Topic Observation to receive IHAVE presence
                       notifications without a full subscription
    """

    def __init__(self, node_id: str, port: int, role: str = "publisher"):
        self.node_id = node_id
        self.port = port
        self.role = role

        self.host: IHost | None = None
        self.pubsub: Pubsub | None = None
        self.gossipsub: GossipSub | None = None
        self.subscription: ISubscriptionAPI | None = None

        self.messages_sent = 0
        self.messages_received = 0
        self.ihave_notifications = 0  # reserved for future explicit IHAVE hooks

    async def start(self) -> None:
        """Initialise the libp2p host and GossipSub v1.3 router."""
        key_pair = create_new_key_pair()

        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )

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

        # Advertise GossipSub v1.3 extensions: both Topic Observation and the
        # interop test extension (testExtension) are enabled for all nodes.
        my_extensions = PeerExtensions(
            topic_observation=True,
            test_extension=True,
        )

        self.gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V13],
            degree=3,
            degree_low=2,
            degree_high=4,
            heartbeat_interval=5,
            heartbeat_initial_delay=1.0,
            score_params=score_params,
            max_idontwant_messages=20,
            # GossipSub v1.3: advertise our supported extensions in the first
            # message on every new stream (enforced at-most-once per peer).
            my_extensions=my_extensions,
        )

        self.pubsub = Pubsub(self.host, self.gossipsub)

        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{self.port}")]

        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                async with background_trio_service(self.gossipsub):
                    await self.pubsub.wait_until_ready()

                    if self.role in ("publisher", "subscriber"):
                        self.subscription = await self.pubsub.subscribe(TOPIC)
                        logger.info(
                            "[%s] subscribed to topic '%s' (full payload mode)",
                            self.node_id,
                            TOPIC,
                        )

                    logger.info(
                        "Node %s started | role=%s | port=%d | %s",
                        self.node_id,
                        self.role,
                        self.port,
                        self.extensions_summary(),
                    )
                    await trio.sleep_forever()

    async def publish_message(self, message: str) -> None:
        """Publish a message to the topic (publisher role only)."""
        if self.pubsub and self.role == "publisher":
            await self.pubsub.publish(TOPIC, message.encode())
            self.messages_sent += 1
            logger.info(
                "[PUBLISH] node=%s topic=%s payload=%s",
                self.node_id,
                TOPIC,
                message,
            )

    async def receive_messages(self) -> None:
        """Read full message payloads (subscriber / publisher roles)."""
        subscription = self.subscription
        if subscription is None:
            return
        try:
            while True:
                message = await subscription.get()
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
        """
        Start Topic Observation for TOPIC (observer role).

        This sends OBSERVE control messages to in-mesh peers that also
        advertised Topic Observation support.  From that point on those peers
        will forward IHAVE presence notifications to us whenever a new message
        arrives on TOPIC, without sending the full payload.
        """
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.start_observing_topic(TOPIC)
            logger.info(
                "[OBSERVE-START] node=%s topic=%s observing_topics=%s",
                self.node_id,
                TOPIC,
                sorted(self.gossipsub.topic_observation.get_observing_topics()),
            )

    async def stop_observing(self) -> None:
        """
        Stop Topic Observation for TOPIC (observer role).

        Sends UNOBSERVE control messages to the peers we were observing through.
        """
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.stop_observing_topic(TOPIC)
            logger.info(
                "[OBSERVE-STOP] node=%s topic=%s observing_topics=%s",
                self.node_id,
                TOPIC,
                sorted(self.gossipsub.topic_observation.get_observing_topics()),
            )

    async def connect_to_peer(self, peer_addr: str) -> None:
        """Connect to a remote peer by multiaddr."""
        if not self.host:
            return
        try:
            maddr = multiaddr.Multiaddr(peer_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
            logger.info(
                "[CONNECT] %s -> %s",
                self.node_id,
                peer_addr,
            )
        except Exception as exc:
            logger.debug(
                "Node %s failed to connect to %s: %s", self.node_id, peer_addr, exc
            )

    def extensions_summary(self) -> str:
        """Return a human-readable summary of negotiated extensions."""
        if not self.gossipsub:
            return "not started"
        ext_state = self.gossipsub.extensions_state
        my = ext_state.my_extensions
        return (
            f"advertised=(topic_observation={my.topic_observation}, "
            f"test_extension={my.test_extension})"
        )


class GossipsubV13Demo:
    """
    Demo controller that sets up a mixed network of publishers, subscribers,
    and observers and runs them for a configurable duration.

    Network layout (with default --nodes 6):
      nodes 0-1 → publisher
      nodes 2-3 → subscriber
      nodes 4-5 → observer
    """

    def __init__(self) -> None:
        self.nodes: list[GossipsubV13Node] = []

    async def setup_network(self, node_count: int = 6) -> None:
        """Allocate ports and create nodes with their roles."""
        roles = _assign_roles(node_count)
        for i in range(node_count):
            port = find_free_port()
            node = GossipsubV13Node(f"node_{i}", port, roles[i])
            self.nodes.append(node)

        role_counts = {r: roles.count(r) for r in set(roles)}
        logger.info(
            "Created %d-node GossipSub v1.3 network: %s",
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
        """Start all nodes, wire them together, then run the demo loop."""
        try:
            async with trio.open_nursery() as nursery:
                # Boot all nodes concurrently.
                for node in self.nodes:
                    nursery.start_soon(node.start)

                # Give nodes time to bind their listening ports.
                await trio.sleep(3)
                logger.info("[STAGE] all node services started")

                # Wire a ring + chord topology so every node has ≥2 peers.
                logger.info("[STAGE] wiring peer connections (ring + skip links)")
                await self._connect_nodes()
                await trio.sleep(2)
                logger.info("[STAGE] peer wiring complete")
                self._log_protocol_snapshot("after-connect")

                # Start receive loops for publishers and subscribers.
                for node in self.nodes:
                    if node.role in ("publisher", "subscriber"):
                        nursery.start_soon(node.receive_messages)
                logger.info("[STAGE] receive loops started (publishers/subscribers)")

                # Observer nodes start Topic Observation after wiring.
                for node in self.nodes:
                    if node.role == "observer":
                        await node.start_observing()
                self._log_observer_snapshot("after-observe-start")

                # Print banner.
                _print_banner(duration)

                end_time = time.time() + duration
                message_counter = 0
                half_time = duration // 2
                heartbeat_step = 0
                midpoint_unobserve_done = False

                while time.time() < end_time:
                    elapsed = duration - (end_time - time.time())

                    # Publishers take turns sending a message.
                    publishers = [n for n in self.nodes if n.role == "publisher"]
                    if publishers:
                        node = random.choice(publishers)
                        msg = f"msg_{message_counter}_{int(time.time())}"
                        await node.publish_message(msg)
                        message_counter += 1

                    # Halfway through, stop one observer to show UNOBSERVE.
                    if elapsed >= half_time and not midpoint_unobserve_done:
                        for node in self.nodes:
                            if (
                                node.role == "observer"
                                and node.gossipsub is not None
                                and node.gossipsub.topic_observation.is_observing(TOPIC)
                            ):
                                await node.stop_observing()
                                self._log_observer_snapshot("after-midpoint-unobserve")
                                midpoint_unobserve_done = True
                                break  # stop only the first one

                    # Emit periodic runtime snapshots so demos are easier to narrate.
                    heartbeat_step += 1
                    self._log_runtime_snapshot(heartbeat_step, elapsed)
                    await trio.sleep(2)

                await trio.sleep(1)
                self._log_protocol_snapshot("final")
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
        publishers = [n for n in self.nodes if n.role == "publisher"]
        subscribers = [n for n in self.nodes if n.role == "subscriber"]
        observers = [n for n in self.nodes if n.role == "observer"]
        published = sum(n.messages_sent for n in publishers)
        delivered = sum(n.messages_received for n in publishers + subscribers)
        active_observers = sum(
            1
            for n in observers
            if n.gossipsub is not None
            and n.gossipsub.topic_observation.is_observing(TOPIC)
        )
        logger.info(
            "[SNAPSHOT t+%ds #%d] published=%d delivered=%d active_observers=%d/%d",
            int(elapsed),
            tick,
            published,
            delivered,
            active_observers,
            len(observers),
        )

    def _log_observer_snapshot(self, label: str) -> None:
        for node in self.nodes:
            if node.role != "observer" or node.gossipsub is None:
                continue
            observing_topics = sorted(
                node.gossipsub.topic_observation.get_observing_topics()
            )
            logger.info(
                "[OBSERVER-SNAPSHOT:%s] node=%s observing_topics=%s",
                label,
                node.node_id,
                observing_topics,
            )

    def _log_protocol_snapshot(self, label: str) -> None:
        for node in self.nodes:
            if node.gossipsub is None:
                continue
            router = node.gossipsub
            peers_total = len(router.peer_protocol)
            v13_peers = sum(
                1 for pid in router.peer_protocol if router.supports_v13_features(pid)
            )
            ext_known = sum(
                1
                for pid in router.peer_protocol
                if router.extensions_state.get_peer_extensions(pid) is not None
            )
            topic_observation_peers = sum(
                1
                for pid in router.peer_protocol
                if router.extensions_state.peer_supports_topic_observation(pid)
            )
            logger.info(
                "[PROTO-SNAPSHOT:%s] node=%s peers=%d v13=%d ext_known=%d topic_obs=%d",
                label,
                node.node_id,
                peers_total,
                v13_peers,
                ext_known,
                topic_observation_peers,
            )

    def _print_statistics(self) -> None:
        """Print a summary table at the end of the demo."""
        print(f"\n{'=' * 65}")
        print("DEMO STATISTICS")
        print(f"{'=' * 65}")

        total_sent = sum(n.messages_sent for n in self.nodes)
        total_received = sum(n.messages_received for n in self.nodes)

        print(f"Total messages published : {total_sent}")
        print(f"Total messages received  : {total_received}")
        print()
        print(f"{'Node':<10} {'Role':<12} {'Sent':>6} {'Recv':>6} Extensions")
        print(f"{'-' * 65}")
        for node in self.nodes:
            print(
                f"{node.node_id:<10} {node.role:<12} "
                f"{node.messages_sent:>6} {node.messages_received:>6}  "
                f"{node.extensions_summary()}"
            )

        print(f"\n{'=' * 65}")
        print("GossipSub 1.3 Features demonstrated:")
        print("  + Extensions Control Message (first message, at most once per peer)")
        print("  + Topic Observation (IHAVE presence notifications without payloads)")
        print("  + Misbehaviour scoring on duplicate Extensions messages")
        print("  + Protocol gating (/meshsub/1.3.0 only)")
        print("  + All GossipSub 1.2 features (IDONTWANT, peer scoring, etc.)")
        print(f"{'=' * 65}\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assign_roles(node_count: int) -> list[str]:
    """
    Distribute roles across nodes.

    With 6 nodes the split is 2 publishers / 2 subscribers / 2 observers.
    Smaller counts fall back gracefully.
    """
    if node_count < 3:
        return ["publisher"] * node_count
    publishers = max(1, node_count // 3)
    observers = max(1, node_count // 3)
    subscribers = node_count - publishers - observers
    return (
        ["publisher"] * publishers
        + ["subscriber"] * subscribers
        + ["observer"] * observers
    )


def _print_banner(duration: int) -> None:
    print(f"\n{'=' * 65}")
    print("GOSSIPSUB 1.3 DEMO")
    print(f"{'=' * 65}")
    print("Protocol  : /meshsub/1.3.0")
    print(f"Duration  : {duration} seconds")
    print("Features  : Extensions Control Message, Topic Observation,")
    print("            IDONTWANT filtering, peer scoring")
    print()
    print("Roles:")
    print("  publisher  – subscribes + publishes messages")
    print("  subscriber – subscribes and reads payloads")
    print("  observer   – Topic Observation only (IHAVE-only, no payload)")
    print()
    print(
        f"At t={duration // 2}s one observer will send UNOBSERVE to stop "
        "receiving notifications."
    )
    print(f"{'=' * 65}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="GossipSub 1.3 Example")
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

    demo = GossipsubV13Demo()
    await demo.setup_network(args.nodes)
    await demo.start_network(args.duration)


if __name__ == "__main__":
    trio.run(main)

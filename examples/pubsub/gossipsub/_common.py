"""
Shared helpers for Gossipsub version demos.

Version scripts keep protocol-specific GossipSub configuration and feature
checklists; host lifecycle, mesh wiring, and demo timing live here.
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable, Sequence
import logging
from typing import Any

import multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost, ISubscriptionAPI
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.tools.anyio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port

logger = logging.getLogger("gossipsub-examples")


def default_topic_score_params() -> dict[str, TopicScoreParams]:
    """Shared P1–P4 topic score defaults used by scoring demos."""
    return {
        "p1_time_in_mesh": TopicScoreParams(weight=0.1, cap=10.0, decay=0.99),
        "p2_first_message_deliveries": TopicScoreParams(
            weight=0.5, cap=20.0, decay=0.99
        ),
        "p3_mesh_message_deliveries": TopicScoreParams(
            weight=0.3, cap=10.0, decay=0.99
        ),
        "p4_invalid_messages": TopicScoreParams(weight=-1.0, cap=50.0, decay=0.99),
    }


def base_score_params(
    *,
    app_specific_score_fn: Callable[[ID], float] | None = None,
    include_p6_p7: bool = False,
) -> ScoreParams:
    """Build ScoreParams with optional P6/P7 and application score."""
    kwargs: dict[str, Any] = {
        **default_topic_score_params(),
        "p5_behavior_penalty_weight": 1.0,
        "p5_behavior_penalty_decay": 0.99,
    }
    if include_p6_p7:
        kwargs.update(
            {
                "p6_appl_slack_weight": 0.5,
                "p6_appl_slack_decay": 0.99,
                "p7_ip_colocation_weight": 0.5,
                "p7_ip_colocation_threshold": 3,
            }
        )
    if app_specific_score_fn is not None:
        kwargs["app_specific_score_fn"] = app_specific_score_fn
    return ScoreParams(**kwargs)


def older_version_router_kwargs() -> dict[str, Any]:
    """
    Explicitly disable features that GossipSub enables by default.

    Older educational demos must not silently inherit adaptive gossip or
    v2.0-style spam/eclipse protection.
    """
    return {
        "adaptive_gossip_enabled": False,
        "spam_protection_enabled": False,
        "eclipse_protection_enabled": False,
    }


class DemoNode:
    """Minimal Gossipsub demo node with publish/receive counters."""

    def __init__(
        self,
        node_id: str,
        port: int,
        *,
        topic: str,
        role: str = "honest",
        fanout_only: bool = False,
        subscribe: bool = True,
    ) -> None:
        self.node_id = node_id
        self.port = port
        self.topic = topic
        self.role = role
        self.fanout_only = fanout_only
        self.subscribe = subscribe and not fanout_only
        self.host: IHost | None = None
        self.pubsub: Pubsub | None = None
        self.gossipsub: GossipSub | None = None
        self.subscription: ISubscriptionAPI | None = None
        self.messages_sent = 0
        self.messages_received = 0
        self.messages_validated = 0
        self.messages_rejected = 0

    def build_gossipsub(self) -> GossipSub:
        """Subclass / caller overrides via assigning before start, or override."""
        raise NotImplementedError

    async def start(self) -> None:
        """Start host, pubsub, and gossipsub; optionally subscribe."""
        key_pair = create_new_key_pair()
        self.host = new_host(
            key_pair=key_pair,
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        self.gossipsub = self.build_gossipsub()
        self.pubsub = Pubsub(self.host, self.gossipsub)
        listen_addrs = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{self.port}")]

        async with self.host.run(listen_addrs=listen_addrs):
            async with background_trio_service(self.pubsub):
                async with background_trio_service(self.gossipsub):
                    await self.pubsub.wait_until_ready()
                    await self.after_ready()
                    if self.subscribe:
                        self.subscription = await self.pubsub.subscribe(self.topic)
                    logger.info(
                        "Node %s (role=%s fanout_only=%s) started on port %s",
                        self.node_id,
                        self.role,
                        self.fanout_only,
                        self.port,
                    )
                    await trio.sleep_forever()

    async def after_ready(self) -> None:
        """Hook for validators / observation setup after pubsub is ready."""
        return None

    async def publish_message(self, message: str) -> None:
        if self.pubsub is None:
            return
        await self.pubsub.publish(self.topic, message.encode())
        self.messages_sent += 1
        logger.info("Node %s (%s) published: %s", self.node_id, self.role, message)

    async def receive_messages(self) -> None:
        subscription = self.subscription
        if subscription is None:
            return
        try:
            while True:
                message = await subscription.get()
                decoded = message.data.decode("utf-8", errors="replace")
                self.messages_received += 1
                if self.on_message(decoded):
                    self.messages_validated += 1
                    logger.info("Node %s received (valid): %s", self.node_id, decoded)
                else:
                    self.messages_rejected += 1
                    logger.warning(
                        "Node %s received (invalid): %s", self.node_id, decoded
                    )
        except Exception as exc:
            logger.debug("Node %s receive loop ended: %s", self.node_id, exc)

    def on_message(self, decoded: str) -> bool:
        """Default: accept all received payloads as valid."""
        return True

    async def connect_to_peer(self, peer_addr: str) -> None:
        if self.host is None:
            return
        try:
            maddr = multiaddr.Multiaddr(peer_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
            logger.debug("Node %s connected to %s", self.node_id, peer_addr)
        except Exception as exc:
            logger.debug(
                "Node %s failed to connect to %s: %s",
                self.node_id,
                peer_addr,
                exc,
            )


class DemoController:
    """Runs a mesh of DemoNode instances for a fixed duration."""

    def __init__(self, nodes: list[DemoNode]) -> None:
        self.nodes = nodes

    async def connect_ring_chord(self) -> None:
        n = len(self.nodes)
        if n < 2:
            return
        for i, node in enumerate(self.nodes):
            for offset in (1, 2):
                if offset >= n:
                    continue
                target = self.nodes[(i + offset) % n]
                if target.host is None or node.host is None:
                    continue
                peer_addr = (
                    f"/ip4/127.0.0.1/tcp/{target.port}/p2p/{target.host.get_id()}"
                )
                await node.connect_to_peer(peer_addr)

    async def run(
        self,
        duration: float,
        *,
        banner_lines: Sequence[str],
        publish_loop: Callable[[DemoController, trio.Nursery, float], Awaitable[None]],
        receive_filter: Callable[[DemoNode], bool] | None = None,
        before_loop: Callable[[DemoController], Awaitable[None]] | None = None,
        after_loop: Callable[[DemoController], None] | None = None,
        settle_boot: float = 3.0,
        settle_mesh: float = 2.0,
    ) -> None:
        try:
            async with trio.open_nursery() as nursery:
                for node in self.nodes:
                    nursery.start_soon(node.start)

                await trio.sleep(settle_boot)
                await self.connect_ring_chord()
                await trio.sleep(settle_mesh)

                for node in self.nodes:
                    if receive_filter is None or receive_filter(node):
                        nursery.start_soon(node.receive_messages)

                if before_loop is not None:
                    await before_loop(self)

                print(flush=True)
                for line in banner_lines:
                    print(line, flush=True)
                print(flush=True)

                await publish_loop(self, nursery, duration)
                await trio.sleep(1.0)
                if after_loop is not None:
                    after_loop(self)
                nursery.cancel_scope.cancel()
        except Exception as exc:
            logger.warning("Demo execution interrupted: %s", exc)


def print_stats_header() -> None:
    print(f"\n{'=' * 60}")
    print("DEMO STATISTICS")
    print(f"{'=' * 60}")


def print_per_node_counts(nodes: Sequence[DemoNode]) -> None:
    total_sent = sum(n.messages_sent for n in nodes)
    total_received = sum(n.messages_received for n in nodes)
    print(f"Total messages sent: {total_sent}")
    print(f"Total messages received: {total_received}")
    print("\nPer-node statistics:")
    for node in nodes:
        extras = ""
        if node.messages_validated or node.messages_rejected:
            extras = (
                f", validated={node.messages_validated}, "
                f"rejected={node.messages_rejected}"
            )
        print(
            f"  {node.node_id} ({node.role}): "
            f"sent={node.messages_sent}, received={node.messages_received}{extras}"
        )


def print_score_table(nodes: Sequence[DemoNode], topic: str) -> None:
    print("\nPeer score snapshot (P1–P7 components where available):")
    for node in nodes:
        if node.gossipsub is None:
            continue
        scorer = node.gossipsub.scorer
        if scorer is None:
            continue
        print(f"  Viewer {node.node_id}:")
        for peer_id in list(node.gossipsub.peer_protocol.keys())[:8]:
            stats = scorer.get_score_stats(peer_id, topic)
            print(
                f"    peer={peer_id.to_base58()[:8]}… "
                f"total={stats['total_score']:.3f} "
                f"app={stats['app_specific_score']:.3f} "
                f"p7={stats['ip_colocation_penalty']:.3f} "
                f"behavior={stats['behavior_penalty']:.3f}"
            )


def parse_demo_args(
    description: str,
    *,
    default_nodes: int = 5,
    default_duration: int = 30,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--nodes",
        type=int,
        default=default_nodes,
        help=f"Number of nodes (default: {default_nodes})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=default_duration,
        help=f"Demo duration in seconds (default: {default_duration})",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def configure_logging(name: str, verbose: bool) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger(name)


def allocate_ports(count: int) -> list[int]:
    return [find_free_port() for _ in range(count)]


async def simple_publish_loop(
    controller: DemoController,
    _nursery: trio.Nursery,
    duration: float,
    *,
    message_fn: Callable[[DemoNode, int], str] | None = None,
    choose_node: Callable[[list[DemoNode]], DemoNode | None] | None = None,
    interval: float = 2.0,
) -> None:
    """Publish until trio deadline; uses trio.current_time()."""
    deadline = trio.current_time() + duration
    counter = 0
    while trio.current_time() < deadline:
        nodes = list(controller.nodes)
        node = choose_node(nodes) if choose_node else (nodes[0] if nodes else None)
        if node is not None:
            payload = message_fn(node, counter) if message_fn else f"msg_{counter}"
            await node.publish_message(payload)
            counter += 1
        await trio.sleep(interval)


def make_gossipsub(
    protocols: Sequence[TProtocol],
    *,
    degree: int = 3,
    degree_low: int = 2,
    degree_high: int = 4,
    score_params: ScoreParams | None = None,
    do_px: bool = False,
    px_peers_count: int = 16,
    prune_back_off: int = 60,
    unsubscribe_back_off: int = 10,
    max_idontwant_messages: int | None = None,
    adaptive_gossip_enabled: bool = False,
    spam_protection_enabled: bool = False,
    eclipse_protection_enabled: bool = False,
    max_messages_per_topic_per_second: float = 10.0,
    min_mesh_diversity_ips: int = 3,
    my_extensions: Any = None,
    **extra: Any,
) -> GossipSub:
    """Factory with safer educational defaults than GossipSub.__init__."""
    kwargs: dict[str, Any] = {
        "protocols": list(protocols),
        "degree": degree,
        "degree_low": degree_low,
        "degree_high": degree_high,
        "heartbeat_interval": 5,
        "heartbeat_initial_delay": 1.0,
        "do_px": do_px,
        "px_peers_count": px_peers_count,
        "prune_back_off": prune_back_off,
        "unsubscribe_back_off": unsubscribe_back_off,
        "adaptive_gossip_enabled": adaptive_gossip_enabled,
        "spam_protection_enabled": spam_protection_enabled,
        "eclipse_protection_enabled": eclipse_protection_enabled,
        "max_messages_per_topic_per_second": max_messages_per_topic_per_second,
        "min_mesh_diversity_ips": min_mesh_diversity_ips,
    }
    if score_params is not None:
        kwargs["score_params"] = score_params
    if max_idontwant_messages is not None:
        kwargs["max_idontwant_messages"] = max_idontwant_messages
    if my_extensions is not None:
        kwargs["my_extensions"] = my_extensions
    kwargs.update(extra)
    return GossipSub(**kwargs)

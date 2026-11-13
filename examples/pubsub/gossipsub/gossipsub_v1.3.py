#!/usr/bin/env python3
"""
GossipSub 1.3 Example

Demonstrates GossipSub v1.3 (/meshsub/1.3.0): Extensions Control Message and
Topic Observation (IHAVE-only observers). Adaptive/spam/eclipse defaults from
newer profiles are explicitly disabled.

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v1.3.py --nodes 6 --duration 40
"""

from __future__ import annotations

import random

import trio

from examples.pubsub.gossipsub._common import (
    DemoController,
    DemoNode,
    allocate_ports,
    base_score_params,
    configure_logging,
    make_gossipsub,
    parse_demo_args,
    print_per_node_counts,
    print_stats_header,
)
from libp2p.pubsub.extensions import PeerExtensions
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V13, GossipSub

TOPIC = "gossipsub-v1.3-demo"


class GossipsubV13Node(DemoNode):
    def build_gossipsub(self) -> GossipSub:
        return make_gossipsub(
            [PROTOCOL_ID_V13],
            score_params=base_score_params(include_p6_p7=False),
            do_px=True,
            max_idontwant_messages=20,
            my_extensions=PeerExtensions(
                topic_observation=True,
                test_extension=True,
            ),
            adaptive_gossip_enabled=False,
            spam_protection_enabled=False,
            eclipse_protection_enabled=False,
        )

    async def start_observing(self) -> None:
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.start_observing_topic(TOPIC)

    async def stop_observing(self) -> None:
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.stop_observing_topic(TOPIC)

    def extensions_summary(self) -> str:
        if not self.gossipsub:
            return "not started"
        my = self.gossipsub.extensions_state.my_extensions
        return (
            f"advertised=(topic_observation={my.topic_observation}, "
            f"test_extension={my.test_extension})"
        )


def _assign_roles(node_count: int) -> list[str]:
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


def _print_feature_checklist() -> None:
    print(f"\n{'=' * 65}")
    print("GossipSub 1.3 Features demonstrated:")
    print("  + Extensions Control Message (first message, at most once per peer)")
    print("  + Topic Observation (IHAVE presence notifications without payloads)")
    print("  + Misbehaviour scoring on duplicate Extensions messages")
    print("  + Protocol gating (/meshsub/1.3.0 only)")
    print("  + All GossipSub 1.2 features (IDONTWANT, peer scoring, etc.)")
    print(f"{'=' * 65}\n")


async def main() -> None:
    args = parse_demo_args(
        "GossipSub 1.3 Example", default_nodes=6, default_duration=40
    )
    configure_logging("gossipsub-v1.3", args.verbose)

    ports = allocate_ports(args.nodes)
    roles = _assign_roles(args.nodes)
    nodes: list[DemoNode] = [
        GossipsubV13Node(
            f"node_{i}",
            ports[i],
            topic=TOPIC,
            role=roles[i],
            subscribe=roles[i] in ("publisher", "subscriber"),
        )
        for i in range(args.nodes)
    ]
    controller = DemoController(nodes)

    async def before_loop(ctrl: DemoController) -> None:
        for node in ctrl.nodes:
            if isinstance(node, GossipsubV13Node) and node.role == "observer":
                await node.start_observing()

    async def publish_loop(
        ctrl: DemoController, nursery: trio.Nursery, duration: float
    ) -> None:
        deadline = trio.current_time() + duration
        half = duration / 2
        counter = 0
        unobserve_done = False
        while trio.current_time() < deadline:
            elapsed = duration - (deadline - trio.current_time())
            publishers = [n for n in ctrl.nodes if n.role == "publisher"]
            if publishers:
                await random.choice(publishers).publish_message(f"msg_{counter}")
                counter += 1
            if elapsed >= half and not unobserve_done:
                for node in ctrl.nodes:
                    if (
                        isinstance(node, GossipsubV13Node)
                        and node.role == "observer"
                        and node.gossipsub is not None
                        and node.gossipsub.topic_observation.is_observing(TOPIC)
                    ):
                        await node.stop_observing()
                        unobserve_done = True
                        break
            await trio.sleep(2.0)

    def after_loop(ctrl: DemoController) -> None:
        print_stats_header()
        print_per_node_counts(ctrl.nodes)
        for node in ctrl.nodes:
            if isinstance(node, GossipsubV13Node):
                print(f"  {node.node_id} extensions: {node.extensions_summary()}")
        _print_feature_checklist()

    await controller.run(
        args.duration,
        banner_lines=[
            "=" * 65,
            "GOSSIPSUB 1.3 DEMO",
            "=" * 65,
            "Protocol  : /meshsub/1.3.0",
            f"Duration  : {args.duration} seconds",
            "Features  : Extensions Control Message, Topic Observation,",
            "            IDONTWANT filtering, peer scoring",
            f"At t={args.duration // 2}s one observer sends UNOBSERVE.",
            "=" * 65,
        ],
        publish_loop=publish_loop,
        receive_filter=lambda n: n.role in ("publisher", "subscriber"),
        before_loop=before_loop,
        after_loop=after_loop,
    )


if __name__ == "__main__":
    trio.run(main)

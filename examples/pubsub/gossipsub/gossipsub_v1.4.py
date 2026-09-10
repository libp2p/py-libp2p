#!/usr/bin/env python3
"""
GossipSub 1.4 Example

Note: `/meshsub/1.4.0` is a py-libp2p experimental profile beyond the upstream
GossipSub spec (which currently standardizes through v1.3). Cross-implementation
interop should not be assumed.

Demonstrates rate limiting, GRAFT flood protection hooks, adaptive gossip, and
Topic Observation inherited from v1.3.

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v1.4.py --nodes 6 --duration 40
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
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V14, GossipSub

TOPIC = "gossipsub-v1.4-demo"
EXPERIMENTAL_NOTE = (
    "Note: GossipSub 1.4 (/meshsub/1.4.0) is an experimental py-libp2p profile, "
    "not part of the official libp2p GossipSub specification."
)


class GossipsubV14Node(DemoNode):
    def build_gossipsub(self) -> GossipSub:
        gossipsub = make_gossipsub(
            [PROTOCOL_ID_V14],
            score_params=base_score_params(include_p6_p7=True),
            do_px=True,
            max_idontwant_messages=20,
            my_extensions=PeerExtensions(
                topic_observation=True,
                test_extension=True,
            ),
            adaptive_gossip_enabled=True,
            spam_protection_enabled=False,
            eclipse_protection_enabled=False,
        )
        # Tighten limits so a short demo can observe rate-limit paths.
        gossipsub.max_iwant_requests_per_second = 5.0
        gossipsub.max_ihave_messages_per_second = 5.0
        gossipsub.graft_flood_threshold = 8.0
        return gossipsub

    async def start_observing(self) -> None:
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.start_observing_topic(TOPIC)

    async def stop_observing(self) -> None:
        if self.gossipsub and self.role == "observer":
            await self.gossipsub.stop_observing_topic(TOPIC)

    def v14_summary(self) -> str:
        gs = self.gossipsub
        if gs is None:
            return "not started"
        return (
            f"health={gs.network_health_score:.2f} gossip_factor={gs.gossip_factor:.2f}"
        )


def _assign_roles(node_count: int) -> list[str]:
    if node_count < 4:
        return (["honest", "validator", "spammer", "observer"] * node_count)[
            :node_count
        ]
    honest = max(1, node_count // 3)
    validators = max(1, node_count // 3)
    observers = 1
    spammers = node_count - honest - validators - observers
    if spammers < 1:
        spammers = 1
        honest = max(1, node_count - validators - observers - spammers)
    return (
        ["honest"] * honest
        + ["validator"] * validators
        + ["spammer"] * spammers
        + ["observer"] * observers
    )


def _print_feature_checklist() -> None:
    print(f"\n{'=' * 65}")
    print(EXPERIMENTAL_NOTE)
    print("GossipSub 1.4 Features demonstrated:")
    print("  + IWANT / IHAVE rate limiting (tightened for demo)")
    print("  + Adaptive gossip factor / health metrics")
    print("  + Topic Observation (from v1.3)")
    print("  + Spammer burst to exercise anti-spam paths")
    print(f"{'=' * 65}\n")


async def main() -> None:
    args = parse_demo_args(
        "GossipSub 1.4 Example", default_nodes=6, default_duration=40
    )
    configure_logging("gossipsub-v1.4", args.verbose)

    ports = allocate_ports(args.nodes)
    roles = _assign_roles(args.nodes)
    nodes: list[DemoNode] = [
        GossipsubV14Node(
            f"node_{i}",
            ports[i],
            topic=TOPIC,
            role=roles[i],
            subscribe=roles[i] != "observer",
        )
        for i in range(args.nodes)
    ]
    controller = DemoController(nodes)

    async def before_loop(ctrl: DemoController) -> None:
        for node in ctrl.nodes:
            if isinstance(node, GossipsubV14Node) and node.role == "observer":
                await node.start_observing()

    async def publish_loop(
        ctrl: DemoController, nursery: trio.Nursery, duration: float
    ) -> None:
        deadline = trio.current_time() + duration
        counter = 0
        spam_burst_done = False
        unobserve_done = False
        while trio.current_time() < deadline:
            elapsed = duration - (deadline - trio.current_time())
            honest = [n for n in ctrl.nodes if n.role == "honest"]
            if honest:
                await random.choice(honest).publish_message(f"msg_{counter}")
                counter += 1
            if elapsed >= duration / 4 and not spam_burst_done:
                for _ in range(12):
                    for spammer in [n for n in ctrl.nodes if n.role == "spammer"]:
                        await spammer.publish_message(f"spam_{counter}")
                        counter += 1
                    await trio.sleep(0.05)
                spam_burst_done = True
            if elapsed >= duration / 2 and not unobserve_done:
                for node in ctrl.nodes:
                    if (
                        isinstance(node, GossipsubV14Node)
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
            if isinstance(node, GossipsubV14Node):
                print(f"  {node.node_id} {node.v14_summary()}")
        _print_feature_checklist()

    await controller.run(
        args.duration,
        banner_lines=[
            "=" * 65,
            "GOSSIPSUB 1.4 DEMO (experimental)",
            "=" * 65,
            EXPERIMENTAL_NOTE,
            "Protocol  : /meshsub/1.4.0",
            f"Duration  : {args.duration} seconds",
            "Features  : rate limits, adaptive gossip, Topic Observation",
            "=" * 65,
        ],
        publish_loop=publish_loop,
        receive_filter=lambda n: n.role in ("honest", "validator", "spammer"),
        before_loop=before_loop,
        after_loop=after_loop,
    )


if __name__ == "__main__":
    trio.run(main)

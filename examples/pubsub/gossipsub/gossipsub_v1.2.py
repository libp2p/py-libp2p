#!/usr/bin/env python3
"""
Gossipsub 1.2 Example

Demonstrates Gossipsub 1.2 (/meshsub/1.2.0): IDONTWANT message filtering on top
of v1.1 peer scoring.

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v1.2.py --nodes 5 --duration 30
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
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V12, GossipSub

TOPIC = "gossipsub-v1.2-demo"


class GossipsubV12Node(DemoNode):
    def build_gossipsub(self) -> GossipSub:
        return make_gossipsub(
            [PROTOCOL_ID_V12],
            score_params=base_score_params(include_p6_p7=False),
            do_px=True,
            max_idontwant_messages=20,
            adaptive_gossip_enabled=False,
            spam_protection_enabled=False,
            eclipse_protection_enabled=False,
        )


def _assign_roles(node_count: int) -> list[str]:
    if node_count < 2:
        return ["honest"] * node_count
    return ["honest"] * (node_count - 1) + ["malicious"]


def _print_feature_checklist() -> None:
    print(f"\n{'=' * 60}")
    print("Gossipsub 1.2 Features:")
    print("  ✓ All Gossipsub 1.1 features (peer scoring)")
    print("  ✓ IDONTWANT message filtering")
    print("  ✓ Reduced redundant traffic in denser meshes")
    print(f"{'=' * 60}\n")


async def main() -> None:
    args = parse_demo_args("Gossipsub 1.2 Example")
    configure_logging("gossipsub-v1.2", args.verbose)

    ports = allocate_ports(args.nodes)
    roles = _assign_roles(args.nodes)
    nodes: list[DemoNode] = [
        GossipsubV12Node(
            f"node_{i}",
            ports[i],
            topic=TOPIC,
            role=roles[i],
        )
        for i in range(args.nodes)
    ]
    controller = DemoController(nodes)

    async def publish_loop(
        ctrl: DemoController, nursery: trio.Nursery, duration: float
    ) -> None:
        deadline = trio.current_time() + duration
        counter = 0
        while trio.current_time() < deadline:
            honest = [n for n in ctrl.nodes if n.role == "honest"]
            if honest:
                await random.choice(honest).publish_message(f"honest_msg_{counter}")
                counter += 1
            malicious = [n for n in ctrl.nodes if n.role == "malicious"]
            if malicious and random.random() < 0.3:
                await malicious[0].publish_message(f"malicious_msg_{counter}")
                counter += 1
            await trio.sleep(2.0)

    def after_loop(ctrl: DemoController) -> None:
        print_stats_header()
        print_per_node_counts(ctrl.nodes)
        _print_feature_checklist()

    await controller.run(
        args.duration,
        banner_lines=[
            "=" * 60,
            "GOSSIPSUB 1.2 DEMO",
            "=" * 60,
            f"Running for {args.duration} seconds...",
            "Protocol: /meshsub/1.2.0",
            "Features: IDONTWANT filtering, peer scoring",
            "=" * 60,
        ],
        publish_loop=publish_loop,
        after_loop=after_loop,
    )


if __name__ == "__main__":
    trio.run(main)

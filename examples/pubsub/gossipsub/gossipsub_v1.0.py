#!/usr/bin/env python3
"""
Gossipsub 1.0 Example

Demonstrates basic Gossipsub 1.0 (/meshsub/1.0.0): mesh pubsub, flooding, and
fanout. A fanout-only publisher (node_0) publishes without subscribing.

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v1.0.py --nodes 5 --duration 30
"""

from __future__ import annotations

import random

import trio

from examples.pubsub.gossipsub._common import (
    DemoController,
    DemoNode,
    allocate_ports,
    configure_logging,
    make_gossipsub,
    parse_demo_args,
    print_per_node_counts,
    print_stats_header,
    simple_publish_loop,
)
from libp2p.pubsub.gossipsub import PROTOCOL_ID, GossipSub

TOPIC = "gossipsub-v1.0-demo"


class GossipsubV10Node(DemoNode):
    def build_gossipsub(self) -> GossipSub:
        return make_gossipsub(
            [PROTOCOL_ID],
            adaptive_gossip_enabled=False,
            spam_protection_enabled=False,
            eclipse_protection_enabled=False,
        )


def _print_feature_checklist() -> None:
    print(f"\n{'=' * 60}")
    print("Gossipsub 1.0 Features:")
    print("  ✓ Basic mesh-based pubsub")
    print("  ✓ Simple message flooding")
    print("  ✓ Mesh topology maintenance")
    print("  ✓ Fanout behaviour: node_0 publishes without subscribing;")
    print("    messages are sent to a random set of topic peers (fanout peers)")
    print("  ✗ No peer scoring")
    print("  ✗ No IDONTWANT support")
    print("  ✗ No adaptive gossip")
    print("  ✗ No advanced security features")
    print(f"{'=' * 60}\n")


async def main() -> None:
    args = parse_demo_args("Gossipsub 1.0 Example")
    configure_logging("gossipsub-v1.0", args.verbose)

    ports = allocate_ports(args.nodes)
    nodes: list[DemoNode] = [
        GossipsubV10Node(
            f"node_{i}",
            ports[i],
            topic=TOPIC,
            role="fanout_publisher" if i == 0 else "subscriber",
            fanout_only=(i == 0),
        )
        for i in range(args.nodes)
    ]
    controller = DemoController(nodes)

    async def publish_loop(
        ctrl: DemoController, nursery: trio.Nursery, duration: float
    ) -> None:
        await simple_publish_loop(
            ctrl,
            nursery,
            duration,
            choose_node=lambda ns: random.choice(ns),
            message_fn=lambda _n, c: f"msg_{c}",
        )

    def after_loop(ctrl: DemoController) -> None:
        print_stats_header()
        print_per_node_counts(ctrl.nodes)
        _print_feature_checklist()

    await controller.run(
        args.duration,
        banner_lines=[
            "=" * 60,
            "GOSSIPSUB 1.0 DEMO",
            "=" * 60,
            f"Running for {args.duration} seconds...",
            "Protocol: /meshsub/1.0.0",
            "Features: Basic mesh-based pubsub, simple flooding, fanout demo",
            "  (node_0 is fanout-only: publishes via fanout, not in mesh)",
            "=" * 60,
        ],
        publish_loop=publish_loop,
        after_loop=after_loop,
    )


if __name__ == "__main__":
    trio.run(main)

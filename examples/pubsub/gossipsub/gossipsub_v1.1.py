#!/usr/bin/env python3
"""
Gossipsub 1.1 Example

Demonstrates Gossipsub 1.1 (/meshsub/1.1.0): peer scoring (P1–P7), prune
backoff, peer exchange (PX), and an application-specific score (P6) based on
node role (validator / honest / malicious).

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v1.1.py --nodes 5 --duration 30
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
    print_score_table,
    print_stats_header,
)
from libp2p.peer.id import ID
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11, GossipSub

TOPIC = "gossipsub-v1.1-demo"

# Role -> P6 application score (demo stand-in for stake / reputation).
_ROLE_APP_SCORE = {
    "validator": 5.0,
    "honest": 1.0,
    "malicious": -2.0,
}


class GossipsubV11Node(DemoNode):
    def build_gossipsub(self) -> GossipSub:
        def app_score(_peer_id: ID) -> float:
            # Peer ID -> role score registry filled after hosts start.
            return _PEER_APP_SCORES.get(_peer_id, 0.0)

        score_params = base_score_params(
            include_p6_p7=True,
            app_specific_score_fn=app_score,
        )
        return make_gossipsub(
            [PROTOCOL_ID_V11],
            score_params=score_params,
            do_px=True,
            px_peers_count=16,
            prune_back_off=60,
            unsubscribe_back_off=10,
            adaptive_gossip_enabled=False,
            spam_protection_enabled=False,
            eclipse_protection_enabled=False,
        )


# Populated after hosts start so P6 can key off peer IDs.
_PEER_APP_SCORES: dict[ID, float] = {}


def _assign_roles(node_count: int) -> list[str]:
    if node_count < 3:
        return ["honest"] * node_count
    roles = ["honest"] * (node_count - 2) + ["malicious", "validator"]
    return roles


def _print_feature_checklist() -> None:
    print(f"\n{'=' * 60}")
    print("Gossipsub 1.1 Features:")
    print("  ✓ Peer scoring (P1–P7)")
    print("  ✓ Behavioral penalties (P5)")
    print("  ✓ P6 application score (role-based demo values)")
    print("  ✓ P7 IP colocation factor")
    print("  ✓ Prune backoff and peer exchange (PX)")
    print("  ✗ No IDONTWANT (v1.2+)")
    print(f"{'=' * 60}\n")


async def main() -> None:
    args = parse_demo_args("Gossipsub 1.1 Example")
    configure_logging("gossipsub-v1.1", args.verbose)

    ports = allocate_ports(args.nodes)
    roles = _assign_roles(args.nodes)
    nodes: list[DemoNode] = [
        GossipsubV11Node(
            f"node_{i}",
            ports[i],
            topic=TOPIC,
            role=roles[i],
        )
        for i in range(args.nodes)
    ]
    controller = DemoController(nodes)

    async def before_loop(ctrl: DemoController) -> None:
        _PEER_APP_SCORES.clear()
        for node in ctrl.nodes:
            if node.host is None:
                continue
            _PEER_APP_SCORES[node.host.get_id()] = _ROLE_APP_SCORE.get(node.role, 0.0)

    async def publish_loop(
        ctrl: DemoController, nursery: trio.Nursery, duration: float
    ) -> None:
        deadline = trio.current_time() + duration
        counter = 0
        while trio.current_time() < deadline:
            honest = [n for n in ctrl.nodes if n.role == "honest"]
            if honest:
                node = random.choice(honest)
                await node.publish_message(f"honest_msg_{counter}")
                counter += 1
            malicious = [n for n in ctrl.nodes if n.role == "malicious"]
            if malicious and random.random() < 0.3:
                await malicious[0].publish_message(f"malicious_msg_{counter}")
                counter += 1
            await trio.sleep(2.0)

    def after_loop(ctrl: DemoController) -> None:
        print_stats_header()
        print_per_node_counts(ctrl.nodes)
        print_score_table(ctrl.nodes, TOPIC)
        _print_feature_checklist()

    await controller.run(
        args.duration,
        banner_lines=[
            "=" * 60,
            "GOSSIPSUB 1.1 DEMO",
            "=" * 60,
            f"Running for {args.duration} seconds...",
            "Protocol: /meshsub/1.1.0",
            "Features: Peer scoring (P1-P7), prune backoff, peer exchange (PX), "
            "optional app score",
            "=" * 60,
        ],
        publish_loop=publish_loop,
        before_loop=before_loop,
        after_loop=after_loop,
    )


if __name__ == "__main__":
    trio.run(main)

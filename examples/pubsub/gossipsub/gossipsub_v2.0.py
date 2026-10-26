#!/usr/bin/env python3
"""
Gossipsub 2.0 Example

Note: GossipSub 2.0 (`/meshsub/2.0.0`) is an experimental/internal protocol
version in py-libp2p, not part of the official libp2p GossipSub specification.
Upstream currently standardizes through v1.3; see discussion #1297 and issue
#920 for py-libp2p context.

This demo enables spam protection and eclipse (IP diversity) options, registers
a real topic validator that rejects crafted payloads, prints peer score
snapshots (P1–P7), and runs honest / spammer / validator roles.

Usage (from repository root):
    python examples/pubsub/gossipsub/gossipsub_v2.0.py --nodes 5 --duration 30
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
from libp2p.pubsub.gossipsub import PROTOCOL_ID_V20, GossipSub
from libp2p.pubsub.pb import rpc_pb2

TOPIC = "gossipsub-v2.0-demo"
EXPERIMENTAL_NOTE = (
    "Note: GossipSub 2.0 (/meshsub/2.0.0) is an experimental/internal protocol "
    "version in py-libp2p, not part of the official libp2p specification."
)

_PEER_APP_SCORES: dict[ID, float] = {}
_ROLE_APP_SCORE = {
    "validator": 5.0,
    "honest": 1.0,
    "spammer": -3.0,
}


def _topic_validator(_peer_id: ID, msg: rpc_pb2.Message) -> bool:
    """Reject payloads marked invalid_ for the demo validation path."""
    try:
        decoded = msg.data.decode("utf-8")
    except Exception:
        return False
    if decoded.startswith("invalid_"):
        return False
    return len(decoded) < 1000


class GossipsubV20Node(DemoNode):
    def build_gossipsub(self) -> GossipSub:
        def app_score(peer_id: ID) -> float:
            return _PEER_APP_SCORES.get(peer_id, 0.0)

        return make_gossipsub(
            [PROTOCOL_ID_V20],
            degree=4,
            degree_low=2,
            degree_high=6,
            score_params=base_score_params(
                include_p6_p7=True,
                app_specific_score_fn=app_score,
            ),
            do_px=True,
            max_idontwant_messages=20,
            adaptive_gossip_enabled=True,
            spam_protection_enabled=True,
            eclipse_protection_enabled=True,
            max_messages_per_topic_per_second=5.0,
            min_mesh_diversity_ips=2,
        )

    async def after_ready(self) -> None:
        if self.pubsub is not None:
            self.pubsub.set_topic_validator(TOPIC, _topic_validator, False)

    def on_message(self, decoded: str) -> bool:
        return not decoded.startswith("invalid_")


def _assign_roles(node_count: int) -> list[str]:
    if node_count < 3:
        return ["honest"] * node_count
    return ["honest"] * (node_count - 2) + ["spammer", "validator"]


def _print_feature_checklist() -> None:
    print(f"\n{'=' * 60}")
    print(EXPERIMENTAL_NOTE)
    print("Gossipsub 2.0 Features (py-libp2p experimental profile):")
    print("  ✓ Peer scoring with P6 (app score) and P7 (IP colocation)")
    print("  ✓ Adaptive gossip enabled")
    print("  ✓ Spam protection with rate limiting")
    print("  ✓ Eclipse protection via IP diversity settings")
    print("  ✓ Topic validator rejecting invalid_* payloads")
    print("  ✗ Equivocation detection not separately demonstrated here")
    print(f"{'=' * 60}\n")


async def main() -> None:
    args = parse_demo_args("Gossipsub 2.0 Example")
    configure_logging("gossipsub-v2.0", args.verbose)

    ports = allocate_ports(args.nodes)
    roles = _assign_roles(args.nodes)
    nodes: list[DemoNode] = [
        GossipsubV20Node(
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
        invalid_sent = False
        while trio.current_time() < deadline:
            honest = [n for n in ctrl.nodes if n.role == "honest"]
            if honest:
                await random.choice(honest).publish_message(f"honest_msg_{counter}")
                counter += 1
            validators = [n for n in ctrl.nodes if n.role == "validator"]
            if validators and random.random() < 0.3:
                await validators[0].publish_message(f"validator_msg_{counter}")
                counter += 1
            spammers = [n for n in ctrl.nodes if n.role == "spammer"]
            if spammers and random.random() < 0.5:
                for _ in range(3):
                    await spammers[0].publish_message(f"spam_msg_{counter}")
                    counter += 1
                    await trio.sleep(0.1)
            if not invalid_sent and honest:
                await honest[0].publish_message(f"invalid_msg_{counter}")
                counter += 1
                invalid_sent = True
            # Periodic score dump mid-run.
            if counter > 0 and counter % 4 == 0:
                print_score_table(ctrl.nodes, TOPIC)
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
            "GOSSIPSUB 2.0 DEMO (experimental)",
            "=" * 60,
            EXPERIMENTAL_NOTE,
            f"Running for {args.duration} seconds...",
            "Protocol: /meshsub/2.0.0",
            "Features: Adaptive gossip, spam/eclipse protection, validators, P6/P7",
            "=" * 60,
        ],
        publish_loop=publish_loop,
        before_loop=before_loop,
        after_loop=after_loop,
    )


if __name__ == "__main__":
    trio.run(main)

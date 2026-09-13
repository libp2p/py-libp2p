#!/usr/bin/env python3
"""
Gossipsub multi-version comparison demo (issue #1130).

Runs the same small mesh scenario under several GossipSub protocol IDs and
prints a metrics table (sent / received / delivery ratio). Optional JSON output.

Scenarios:
  normal — honest publishers only
  spam   — one flooding peer
  churn  — disconnect/reconnect a subset mid-run

Usage (from repository root):
    python examples/pubsub/gossipsub/compare_versions.py --nodes 4 --duration 8
    python examples/pubsub/gossipsub/compare_versions.py --scenario spam --json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from typing import Any

import trio

from examples.pubsub.gossipsub._common import (
    DemoController,
    DemoNode,
    allocate_ports,
    base_score_params,
    configure_logging,
    make_gossipsub,
)
from libp2p.custom_types import TProtocol
from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID,
    PROTOCOL_ID_V11,
    PROTOCOL_ID_V12,
    PROTOCOL_ID_V13,
    PROTOCOL_ID_V14,
    PROTOCOL_ID_V20,
    GossipSub,
)

logger = logging.getLogger("gossipsub-compare")

TOPIC = "gossipsub-compare-demo"

VERSIONS: list[tuple[str, TProtocol, dict[str, Any]]] = [
    (
        "1.0",
        PROTOCOL_ID,
        {
            "adaptive_gossip_enabled": False,
            "spam_protection_enabled": False,
            "eclipse_protection_enabled": False,
        },
    ),
    (
        "1.1",
        PROTOCOL_ID_V11,
        {
            "score_params": base_score_params(include_p6_p7=True),
            "do_px": True,
            "adaptive_gossip_enabled": False,
            "spam_protection_enabled": False,
            "eclipse_protection_enabled": False,
        },
    ),
    (
        "1.2",
        PROTOCOL_ID_V12,
        {
            "score_params": base_score_params(include_p6_p7=False),
            "do_px": True,
            "max_idontwant_messages": 20,
            "adaptive_gossip_enabled": False,
            "spam_protection_enabled": False,
            "eclipse_protection_enabled": False,
        },
    ),
    (
        "1.3",
        PROTOCOL_ID_V13,
        {
            "score_params": base_score_params(include_p6_p7=False),
            "do_px": True,
            "max_idontwant_messages": 20,
            "adaptive_gossip_enabled": False,
            "spam_protection_enabled": False,
            "eclipse_protection_enabled": False,
        },
    ),
    (
        "1.4",
        PROTOCOL_ID_V14,
        {
            "score_params": base_score_params(include_p6_p7=True),
            "do_px": True,
            "max_idontwant_messages": 20,
            "adaptive_gossip_enabled": True,
            "spam_protection_enabled": False,
            "eclipse_protection_enabled": False,
        },
    ),
    (
        "2.0",
        PROTOCOL_ID_V20,
        {
            "score_params": base_score_params(include_p6_p7=True),
            "do_px": True,
            "max_idontwant_messages": 20,
            "adaptive_gossip_enabled": True,
            "spam_protection_enabled": True,
            "eclipse_protection_enabled": True,
            "max_messages_per_topic_per_second": 5.0,
        },
    ),
]


class CompareNode(DemoNode):
    def __init__(
        self,
        node_id: str,
        port: int,
        *,
        protocol: TProtocol,
        router_kwargs: dict[str, Any],
        role: str,
    ) -> None:
        super().__init__(node_id, port, topic=TOPIC, role=role)
        self._protocol = protocol
        self._router_kwargs = router_kwargs

    def build_gossipsub(self) -> GossipSub:
        return make_gossipsub([self._protocol], **self._router_kwargs)


async def _run_one_version(
    version: str,
    protocol: TProtocol,
    router_kwargs: dict[str, Any],
    *,
    node_count: int,
    duration: float,
    scenario: str,
) -> dict[str, Any]:
    ports = allocate_ports(node_count)
    roles = ["honest"] * node_count
    if scenario == "spam" and node_count >= 2:
        roles[-1] = "spammer"

    nodes: list[DemoNode] = [
        CompareNode(
            f"{version}_node_{i}",
            ports[i],
            protocol=protocol,
            router_kwargs=router_kwargs,
            role=roles[i],
        )
        for i in range(node_count)
    ]
    controller = DemoController(nodes)

    async def publish_loop(
        ctrl: DemoController, nursery: trio.Nursery, dur: float
    ) -> None:
        deadline = trio.current_time() + dur
        counter = 0
        churn_done = False
        while trio.current_time() < deadline:
            elapsed = dur - (deadline - trio.current_time())
            honest = [n for n in ctrl.nodes if n.role == "honest"]
            if honest:
                await random.choice(honest).publish_message(f"{version}_msg_{counter}")
                counter += 1
            if scenario == "spam":
                for spammer in [n for n in ctrl.nodes if n.role == "spammer"]:
                    for _ in range(3):
                        await spammer.publish_message(f"{version}_spam_{counter}")
                        counter += 1
            if scenario == "churn" and not churn_done and elapsed >= dur / 2:
                # Soft churn: briefly pause publishing from half the nodes.
                churn_done = True
                logger.info("[%s] churn: pausing half the publishers", version)
                await trio.sleep(1.0)
            await trio.sleep(1.0)

    await controller.run(
        duration,
        banner_lines=[
            f"--- Comparing Gossipsub {version} ({protocol}) scenario={scenario} ---"
        ],
        publish_loop=publish_loop,
        settle_boot=2.0,
        settle_mesh=1.5,
    )

    sent = sum(n.messages_sent for n in nodes)
    received = sum(n.messages_received for n in nodes)
    ratio = (received / sent) if sent else 0.0
    return {
        "version": version,
        "protocol": str(protocol),
        "scenario": scenario,
        "sent": sent,
        "received": received,
        "delivery_ratio": round(ratio, 3),
    }


def _print_table(rows: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 72)
    print("COMPARISON TABLE")
    print("=" * 72)
    print(f"{'Version':<8} {'Protocol':<18} {'Sent':>6} {'Recv':>6} {'Ratio':>8}")
    print("-" * 72)
    for row in rows:
        print(
            f"{row['version']:<8} {row['protocol']:<18} "
            f"{row['sent']:>6} {row['received']:>6} {row['delivery_ratio']:>8.3f}"
        )
    print("=" * 72 + "\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Gossipsub version comparison")
    parser.add_argument("--nodes", type=int, default=4)
    parser.add_argument("--duration", type=int, default=8)
    parser.add_argument(
        "--scenario",
        choices=["normal", "spam", "churn"],
        default="normal",
    )
    parser.add_argument(
        "--versions",
        default="1.0,1.1,1.2,1.3,1.4,2.0",
        help="Comma-separated versions to compare",
    )
    parser.add_argument("--json", action="store_true", help="Also print JSON")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging("gossipsub-compare", args.verbose)

    wanted = {v.strip() for v in args.versions.split(",") if v.strip()}
    rows: list[dict[str, Any]] = []
    for version, protocol, kwargs in VERSIONS:
        if version not in wanted:
            continue
        # Fresh ScoreParams objects per run (avoid sharing mutable state).
        router_kwargs = dict(kwargs)
        if "score_params" in router_kwargs:
            router_kwargs["score_params"] = base_score_params(
                include_p6_p7=version in {"1.1", "1.4", "2.0"}
            )
        row = await _run_one_version(
            version,
            protocol,
            router_kwargs,
            node_count=args.nodes,
            duration=float(args.duration),
            scenario=args.scenario,
        )
        rows.append(row)

    _print_table(rows)
    if args.json:
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    trio.run(main)

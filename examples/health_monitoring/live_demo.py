"""
Live connection-health demo: one hub plus N-1 leaf peers on local TCP.

Unlike ``basic_example.py`` (config-only) this script:

1. Enables the opt-in Python health monitor with short intervals
2. Connects a configurable number of local TCP hosts (default 25)
3. Runs selected scenarios (default: all): healthy mesh, a no-monitor
   observer, ConnMgr Protect, concurrent echo traffic, and peer churn
4. Prints live peer / network health after the monitor pings

Usage:
    python -m examples.health_monitoring.live_demo
    python -m examples.health_monitoring.live_demo --peers 25 --scenario all
    python -m examples.health_monitoring.live_demo --peers 10 --scenario healthy
    python -m examples.health_monitoring.live_demo --scenario protect,churn
    # or, after install: health-monitoring-demo
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
import logging
import secrets
from typing import Any, TypeVar

import multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.config import ConnectionConfig
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.address_validation import find_free_port

logging.basicConfig(level=logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)

ECHO_PROTOCOL = TProtocol("/health-demo/echo/1.0.0")
PROTECT_TAG = "health-demo"
DEFAULT_PEERS = 25
ALL_SCENARIOS = ("healthy", "disabled", "protect", "traffic", "churn")
_T = TypeVar("_T")
_R = TypeVar("_R")


@dataclass(frozen=True)
class DemoOptions:
    """Runtime options for the live health demo."""

    peers: int = DEFAULT_PEERS
    scenarios: tuple[str, ...] = ALL_SCENARIOS
    wait_for_monitor: float = 1.5
    protect_count: int = 5
    churn_count: int = 5
    streams_per_peer: int = 3
    strategy: str = "health_based"
    connect_limit: int = 8


def parse_scenarios(raw: str | Sequence[str]) -> tuple[str, ...]:
    """Parse ``all`` or a comma/space-separated scenario list."""
    if isinstance(raw, str):
        tokens = [t.strip().lower() for t in raw.replace(",", " ").split() if t.strip()]
    else:
        tokens = [str(t).strip().lower() for t in raw if str(t).strip()]

    if not tokens or tokens == ["all"]:
        return ALL_SCENARIOS

    unknown = [t for t in tokens if t not in ALL_SCENARIOS]
    if unknown:
        valid = ", ".join(ALL_SCENARIOS)
        raise ValueError(f"Unknown scenario(s) {unknown!r}. Valid: {valid}, all")

    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return tuple(ordered)


def _health_config(*, strategy: str) -> ConnectionConfig:
    """Fast intervals so a live run finishes in a few seconds."""
    return ConnectionConfig(
        enable_health_monitoring=True,
        health_initial_delay=0.2,
        health_warmup_window=0.0,
        health_check_interval=0.4,
        ping_timeout=2.0,
        min_health_threshold=0.3,
        min_connections_per_peer=1,
        load_balancing_strategy=strategy,
        max_connections_per_peer=3,
    )


def _disabled_config() -> ConnectionConfig:
    return ConnectionConfig(enable_health_monitoring=False)


def _short_id(host_or_id: IHost | ID) -> str:
    if isinstance(host_or_id, ID):
        return str(host_or_id)[:16]
    return str(host_or_id.get_id())[:16]


def _print_banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _print_health(title: str, summary: dict[str, Any]) -> None:
    print(f"\n  {title}")
    if not summary:
        print("    (empty — health monitoring disabled or no connections yet)")
        return
    peers = summary.get("total_peers", summary.get("connection_count", "?"))
    conns = summary.get("total_connections", summary.get("connection_count", "?"))
    print(f"    peers / connections: {peers} / {conns}")
    if "average_peer_health" in summary:
        print(f"    average peer health: {summary['average_peer_health']:.3f}")
        print(f"    peers with issues: {summary.get('peers_with_issues', 0)}")
    if "average_health_score" in summary:
        score = summary["average_health_score"]
        latency = summary.get("average_latency_ms", 0)
        success = summary.get("average_success_rate", 0)
        print(f"    average health score: {score:.3f}")
        print(f"    average latency ms: {latency:.1f}")
        print(f"    average success rate: {success:.2f}")
        print(f"    unhealthy connections: {summary.get('unhealthy_connections', 0)}")


def _print_peer_table(
    hub: IHost,
    leaves: Sequence[IHost],
    *,
    protected_ids: set[ID] | None = None,
) -> None:
    swarm = hub.get_network()
    protected_ids = protected_ids or set()
    print("\n    peer              conns  health  latency  success  protected")
    for leaf in leaves:
        peer_id = leaf.get_id()
        health = hub.get_connection_health(peer_id)
        if not health:
            conns = len(swarm.get_connections(peer_id))
            flag = "yes" if swarm.is_protected(peer_id) else "no"
            print(
                f"    {_short_id(peer_id):<16}  {conns:>5}       -       -"
                f"        -  {flag}"
            )
            continue
        is_prot = peer_id in protected_ids or swarm.is_protected(peer_id)
        flag = "yes" if is_prot else "no"
        print(
            f"    {_short_id(peer_id):<16}  "
            f"{health.get('connection_count', 0):>5}  "
            f"{health.get('average_health_score', 0):>6.3f}  "
            f"{health.get('average_latency_ms', 0):>7.1f}  "
            f"{health.get('average_success_rate', 0):>7.2f}  {flag}"
        )


async def _echo_handler(stream: INetStream) -> None:
    try:
        data = await stream.read(1024)
        await stream.write(data)
    finally:
        await stream.close()


async def _echo(hub: IHost, peer_id: ID, payload: bytes) -> bytes:
    stream = await hub.new_stream(peer_id, [ECHO_PROTOCOL])
    echoed = b""
    try:
        await stream.write(payload)
        echoed = await stream.read(len(payload))
    finally:
        await stream.close()
    return echoed


async def _run_limited(
    items: Sequence[_T],
    worker: Callable[[_T], Awaitable[_R]],
    *,
    limit: int,
) -> list[_R]:
    results: list[_R] = []
    limiter = trio.CapacityLimiter(max(1, limit))

    async def _one(item: _T) -> None:
        async with limiter:
            results.append(await worker(item))

    async with trio.open_nursery() as nursery:
        for item in items:
            nursery.start_soon(_one, item)

    return results


def _new_host(*, health: bool, strategy: str) -> IHost:
    config = _health_config(strategy=strategy) if health else _disabled_config()
    host = new_host(
        key_pair=create_new_key_pair(secrets.token_bytes(32)),
        connection_config=config,
    )
    host.set_stream_handler(ECHO_PROTOCOL, _echo_handler)
    return host


def _listen_addr() -> list[multiaddr.Multiaddr]:
    port = find_free_port()
    return [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]


async def _connect_leaves(hub: IHost, leaves: Sequence[IHost], *, limit: int) -> None:
    async def _connect(leaf: IHost) -> ID:
        await hub.connect(PeerInfo(leaf.get_id(), leaf.get_addrs()))
        return leaf.get_id()

    await _run_limited(leaves, _connect, limit=limit)


async def _echo_leaves(
    hub: IHost, leaves: Sequence[IHost], payload: bytes, *, limit: int
) -> list[bytes]:
    async def _one(leaf: IHost) -> bytes:
        return await _echo(hub, leaf.get_id(), payload)

    return await _run_limited(leaves, _one, limit=limit)


def _clamp_counts(options: DemoOptions, leaf_count: int) -> tuple[int, int]:
    protect_n = min(max(0, options.protect_count), leaf_count)
    remaining_after_protect = leaf_count - protect_n
    # Prefer churning unprotected peers; keep at least one leaf if possible.
    max_churn = max(0, leaf_count - 1)
    if remaining_after_protect > 0:
        max_churn = min(max_churn, remaining_after_protect)
    churn_n = min(max(0, options.churn_count), max_churn)
    return protect_n, churn_n


async def _scenario_healthy(
    hub: IHost,
    leaves: Sequence[IHost],
    options: DemoOptions,
    payload: bytes,
) -> dict[str, Any]:
    _print_banner("Scenario: healthy")
    print(f"  Echoing {payload!r} to {len(leaves)} leaf peers...")
    echoed = await _echo_leaves(hub, leaves, payload, limit=options.connect_limit)
    ok = sum(1 for item in echoed if item == payload)
    print(f"  Echo round-trips: {ok}/{len(leaves)} ok")

    print(f"\n  Waiting {options.wait_for_monitor:.1f}s for health monitor pings...")
    await trio.sleep(options.wait_for_monitor)

    network_health = hub.get_network_health_summary()
    monitor_status = await hub.get_health_monitor_status()
    _print_health("network summary", network_health)
    print("\n  Monitor status:")
    print(f"    enabled: {monitor_status.get('enabled')}")
    print(f"    monitored connections: {monitor_status.get('monitored_connections')}")
    print(f"    check interval s: {monitor_status.get('check_interval_seconds')}")
    _print_peer_table(hub, leaves)

    sample_peer = hub.get_connection_health(leaves[0].get_id()) if leaves else {}
    return {
        "echo_ok": ok,
        "echoed_sample": echoed[0] if echoed else b"",
        "network_health": network_health,
        "monitor_status": monitor_status,
        "peer_health": sample_peer,
        "total_connections": hub.get_network().get_total_connections(),
    }


async def _scenario_protect(
    hub: IHost,
    leaves: Sequence[IHost],
    protect_n: int,
) -> dict[str, Any]:
    _print_banner("Scenario: protect")
    swarm = hub.get_network()
    protected_leaves = list(leaves[:protect_n])
    for leaf in protected_leaves:
        swarm.protect(leaf.get_id(), PROTECT_TAG)

    protected_ids = {leaf.get_id() for leaf in protected_leaves}
    protected = sum(1 for leaf in leaves if swarm.is_protected(leaf.get_id()))
    print(
        f"  ConnMgr Protect: tagged {protected}/{len(leaves)} leaves "
        f"(tag={PROTECT_TAG!r})"
    )
    print("  Auto-replace of unhealthy conns skips protected peers.")
    _print_peer_table(hub, leaves, protected_ids=protected_ids)
    return {
        "protected": protected > 0,
        "protected_count": protected,
        "protected_ids": [str(peer_id) for peer_id in protected_ids],
    }


async def _scenario_traffic(
    hub: IHost,
    leaves: Sequence[IHost],
    options: DemoOptions,
    payload: bytes,
) -> dict[str, Any]:
    _print_banner("Scenario: traffic")
    total = len(leaves) * options.streams_per_peer
    print(
        f"  Concurrent echo burst: {options.streams_per_peer} streams x "
        f"{len(leaves)} peers ({total} round-trips)..."
    )
    counts = {"ok": 0, "fail": 0}
    limiter = trio.CapacityLimiter(max(1, options.connect_limit * 2))

    async def _one(leaf: IHost) -> None:
        async with limiter:
            try:
                echoed = await _echo(hub, leaf.get_id(), payload)
                if echoed == payload:
                    counts["ok"] += 1
                else:
                    counts["fail"] += 1
            except Exception:
                counts["fail"] += 1

    async with trio.open_nursery() as nursery:
        for leaf in leaves:
            for _ in range(options.streams_per_peer):
                nursery.start_soon(_one, leaf)

    print(f"  Burst result: {counts['ok']} ok / {counts['fail']} failed")
    await trio.sleep(min(0.5, options.wait_for_monitor))
    network_health = hub.get_network_health_summary()
    _print_health("network summary after traffic", network_health)
    return {
        "echo_ok": counts["ok"],
        "echo_fail": counts["fail"],
        "network_health": network_health,
    }


async def _scenario_churn(
    hub: IHost,
    churn_leaves: Sequence[IHost],
    remaining: Sequence[IHost],
    options: DemoOptions,
) -> dict[str, Any]:
    _print_banner("Scenario: churn")
    swarm = hub.get_network()
    before = swarm.get_total_connections()
    print(f"  Closing {len(churn_leaves)} leaf peer(s); {len(remaining)} remain...")
    for leaf in churn_leaves:
        await swarm.close_peer(leaf.get_id())

    print(f"  Waiting {options.wait_for_monitor:.1f}s after churn...")
    await trio.sleep(options.wait_for_monitor)

    after = swarm.get_total_connections()
    network_health = hub.get_network_health_summary()
    print(f"  Connections: {before} → {after}")
    _print_health("network summary after churn", network_health)
    if remaining:
        _print_peer_table(hub, remaining)
    return {
        "churned": len(churn_leaves),
        "connections_before": before,
        "connections_after": after,
        "network_health": network_health,
    }


async def _scenario_disabled(
    observer: IHost,
    leaves: Sequence[IHost],
    hub: IHost,
    options: DemoOptions,
) -> dict[str, Any]:
    _print_banner("Scenario: disabled")
    sample = list(leaves[: min(3, len(leaves))])
    print(
        f"  Observer host has health monitoring OFF; dialing {len(sample)} "
        "leaf peer(s)..."
    )
    await _connect_leaves(observer, sample, limit=options.connect_limit)
    empty = observer.get_network_health_summary()
    live = hub.get_network_health_summary()
    _print_health("observer (monitoring disabled)", empty)
    _print_health("hub (monitoring enabled)", live)
    return {
        "observer_health": empty,
        "hub_health": live,
        "observer_connections": observer.get_network().get_total_connections(),
    }


async def run_live_demo(
    *,
    peers: int = DEFAULT_PEERS,
    scenarios: str | Sequence[str] = "all",
    wait_for_monitor: float = 1.5,
    protect_count: int = 5,
    churn_count: int = 5,
    streams_per_peer: int = 3,
    strategy: str = "health_based",
    connect_limit: int = 8,
) -> dict[str, Any]:
    """
    Run the live multi-peer health demo.

    Returns a dict of observed health/monitor state for tests.
    """
    scenario_list = parse_scenarios(scenarios)
    if peers < 2:
        raise ValueError("peers must be at least 2 (one hub + one leaf)")

    options = DemoOptions(
        peers=peers,
        scenarios=scenario_list,
        wait_for_monitor=wait_for_monitor,
        protect_count=protect_count,
        churn_count=churn_count,
        streams_per_peer=streams_per_peer,
        strategy=strategy,
        connect_limit=connect_limit,
    )
    leaf_count = peers - 1
    protect_n, churn_n = _clamp_counts(options, leaf_count)
    payload = b"health-demo"

    hub = _new_host(health=True, strategy=strategy)
    leaves = [_new_host(health=False, strategy=strategy) for _ in range(leaf_count)]
    observer: IHost | None = None
    if "disabled" in scenario_list:
        observer = _new_host(health=False, strategy=strategy)

    _print_banner("Connection Health Monitoring — live demo")
    print(f"  Hub:    {_short_id(hub)}...")
    print(f"  Leaves: {leaf_count}  (total peers={peers})")
    print(f"  Scenarios: {', '.join(scenario_list)}")
    print(f"  Strategy: {strategy}  |  monitor interval: 0.4s")

    result: dict[str, Any] = {
        "peers": peers,
        "scenarios": list(scenario_list),
        "echoed": payload,
        "total_connections": 0,
        "protected": False,
        "peer_health": {},
        "network_health": {},
        "monitor_status": {"enabled": False},
        "json_metrics": "{}",
    }

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(hub.run(listen_addrs=_listen_addr()))
        for leaf in leaves:
            await stack.enter_async_context(leaf.run(listen_addrs=_listen_addr()))
        if observer is not None:
            await stack.enter_async_context(observer.run(listen_addrs=_listen_addr()))

        print("\n  Hosts listening. Connecting hub → leaves...")
        await _connect_leaves(hub, leaves, limit=options.connect_limit)
        swarm = hub.get_network()
        print(f"  Connected. Hub connections: {swarm.get_total_connections()}")
        result["total_connections"] = swarm.get_total_connections()

        remaining_leaves: list[IHost] = list(leaves)
        protected_leaves: list[IHost] = []

        if "healthy" in scenario_list:
            healthy = await _scenario_healthy(hub, remaining_leaves, options, payload)
            result["healthy"] = healthy
            result["echoed"] = healthy.get("echoed_sample", payload)
            result["peer_health"] = healthy["peer_health"]
            result["network_health"] = healthy["network_health"]
            result["monitor_status"] = healthy["monitor_status"]
            result["total_connections"] = healthy["total_connections"]
        else:
            await trio.sleep(options.wait_for_monitor)
            result["network_health"] = hub.get_network_health_summary()
            result["monitor_status"] = await hub.get_health_monitor_status()
            if remaining_leaves:
                result["peer_health"] = hub.get_connection_health(
                    remaining_leaves[0].get_id()
                )

        if "disabled" in scenario_list and observer is not None:
            result["disabled"] = await _scenario_disabled(
                observer, remaining_leaves, hub, options
            )

        if "protect" in scenario_list:
            protected = await _scenario_protect(hub, remaining_leaves, protect_n)
            result["protect"] = protected
            result["protected"] = protected["protected"]
            protected_leaves = remaining_leaves[:protect_n]

        if "traffic" in scenario_list:
            result["traffic"] = await _scenario_traffic(
                hub, remaining_leaves, options, payload
            )

        if "churn" in scenario_list:
            protected_ids = {leaf.get_id() for leaf in protected_leaves}
            churn_candidates = [
                leaf for leaf in remaining_leaves if leaf.get_id() not in protected_ids
            ]
            if len(churn_candidates) < churn_n:
                churn_candidates = list(remaining_leaves)
            churn_leaves = churn_candidates[:churn_n]
            churn_ids = {leaf.get_id() for leaf in churn_leaves}
            remaining_leaves = [
                leaf for leaf in remaining_leaves if leaf.get_id() not in churn_ids
            ]
            result["churn"] = await _scenario_churn(
                hub, churn_leaves, remaining_leaves, options
            )
            result["total_connections"] = result["churn"]["connections_after"]
            result["network_health"] = result["churn"]["network_health"]

        result["json_metrics"] = hub.export_health_metrics("json")
        result["total_connections"] = hub.get_network().get_total_connections()

        print("\n  Demo complete.")
        print("  Takeaways:")
        print("    1. Health monitoring is off by default; enable via ConnectionConfig")
        print("    2. Scores update after the background monitor pings idle conns")
        print("    3. Protect() is ConnMgr importance — health must not fight it")
        print("    4. Default LB 'best' matches go-libp2p; health_based is Python-only")
        print()

    return result


def build_parser() -> argparse.ArgumentParser:
    scenario_help = (
        f"Comma-separated scenarios, or 'all'. Available: {', '.join(ALL_SCENARIOS)}"
    )
    parser = argparse.ArgumentParser(
        description="Live multi-peer connection health demo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m examples.health_monitoring.live_demo\n"
            "  python -m examples.health_monitoring.live_demo --peers 25 "
            "--scenario all\n"
            "  python -m examples.health_monitoring.live_demo --peers 10 "
            "--scenario healthy,protect\n"
            "  python -m examples.health_monitoring.live_demo "
            "--scenario churn --churn-count 8\n"
        ),
    )
    parser.add_argument(
        "--peers",
        type=int,
        default=DEFAULT_PEERS,
        help=f"Total local hosts including the hub (default: {DEFAULT_PEERS})",
    )
    parser.add_argument(
        "--scenario",
        default="all",
        help=scenario_help,
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1.5,
        dest="wait_for_monitor",
        help="Seconds to wait for monitor pings (default: 1.5)",
    )
    parser.add_argument(
        "--protect-count",
        type=int,
        default=5,
        help="Leaves to ConnMgr-protect in the protect scenario (default: 5)",
    )
    parser.add_argument(
        "--churn-count",
        type=int,
        default=5,
        help="Leaves to disconnect in the churn scenario (default: 5)",
    )
    parser.add_argument(
        "--streams-per-peer",
        type=int,
        default=3,
        help="Concurrent echo streams per leaf in traffic (default: 3)",
    )
    parser.add_argument(
        "--strategy",
        default="health_based",
        choices=(
            "best",
            "round_robin",
            "least_loaded",
            "health_based",
            "latency_based",
        ),
        help="Load-balancing strategy (default: health_based)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print available scenarios and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_scenarios:
        print("Available scenarios:")
        for name in ALL_SCENARIOS:
            print(f"  {name}")
        print("  all")
        return

    async def _run() -> None:
        await run_live_demo(
            peers=args.peers,
            scenarios=args.scenario,
            wait_for_monitor=args.wait_for_monitor,
            protect_count=args.protect_count,
            churn_count=args.churn_count,
            streams_per_peer=args.streams_per_peer,
            strategy=args.strategy,
        )

    trio.run(_run)


if __name__ == "__main__":
    main()

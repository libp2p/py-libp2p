from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from typing import Any

from .bootstrap import (
    get_bootstrap_addresses,
    get_runtime_bootstrap_addresses,
)
from .constants import (
    FIL_CHAIN_EXCHANGE_PROTOCOL,
    FIL_HELLO_PROTOCOL,
    blocks_topic,
    dht_protocol_name,
    messages_topic,
)
from .networks import get_network_preset
from .pubsub import (
    build_filecoin_gossipsub,
    build_filecoin_score_params,
)


def _effective_network_name(
    network_alias: str, explicit_network_name: str | None
) -> str:
    if explicit_network_name:
        return explicit_network_name
    return get_network_preset(network_alias).genesis_network_name


def _dump_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _cmd_topics(args: argparse.Namespace) -> int:
    network_name = _effective_network_name(args.network, args.network_name)
    payload = {
        "network_alias": args.network,
        "network_name": network_name,
        "blocks_topic": blocks_topic(network_name),
        "messages_topic": messages_topic(network_name),
        "dht_protocol": str(dht_protocol_name(network_name)),
    }

    if args.json:
        _dump_json(payload)
    else:
        print(f"network_alias: {payload['network_alias']}")
        print(f"network_name: {payload['network_name']}")
        print(f"blocks_topic: {payload['blocks_topic']}")
        print(f"messages_topic: {payload['messages_topic']}")
        print(f"dht_protocol: {payload['dht_protocol']}")
    return 0


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    if args.canonical:
        addrs = get_bootstrap_addresses(args.network, canonical=True)
        mode = "canonical"
    else:
        addrs = get_runtime_bootstrap_addresses(
            args.network,
            resolve_dns=args.resolve_dns,
            include_quic=args.include_quic,
        )
        mode = "runtime"

    if args.json:
        _dump_json(
            {
                "network_alias": args.network,
                "mode": mode,
                "count": len(addrs),
                "addresses": addrs,
            }
        )
    else:
        for addr in addrs:
            print(addr)
    return 0


def _cmd_preset(args: argparse.Namespace) -> int:
    preset = get_network_preset(args.network)
    network_name = _effective_network_name(args.network, args.network_name)
    score_params = build_filecoin_score_params(mode=args.score_mode)
    gossipsub = build_filecoin_gossipsub(
        network_name=network_name,
        bootstrapper=args.bootstrapper,
        score_mode=args.score_mode,
    )

    payload = {
        "network": {
            "alias": preset.name,
            "genesis_network_name": preset.genesis_network_name,
            "effective_network_name": network_name,
        },
        "protocols": {
            "hello": str(FIL_HELLO_PROTOCOL),
            "chain_exchange": str(FIL_CHAIN_EXCHANGE_PROTOCOL),
        },
        "topics": {
            "blocks": blocks_topic(network_name),
            "messages": messages_topic(network_name),
            "dht": str(dht_protocol_name(network_name)),
        },
        "gossipsub": {
            "degree": gossipsub.degree,
            "degree_low": gossipsub.degree_low,
            "degree_high": gossipsub.degree_high,
            "direct_connect_initial_delay": gossipsub.direct_connect_initial_delay,
            "gossip_history": gossipsub.mcache.history_size,
            "do_px": gossipsub.do_px,
            "protocols": [str(protocol) for protocol in gossipsub.protocols],
        },
        "score": {
            "mode": args.score_mode,
            "publish_threshold": score_params.publish_threshold,
            "gossip_threshold": score_params.gossip_threshold,
            "graylist_threshold": score_params.graylist_threshold,
            "accept_px_threshold": score_params.accept_px_threshold,
        },
    }

    if args.json:
        _dump_json(payload)
    else:
        print(f"network_alias: {preset.name}")
        print(f"genesis_network_name: {preset.genesis_network_name}")
        print(f"effective_network_name: {network_name}")
        print(f"hello_protocol: {FIL_HELLO_PROTOCOL}")
        print(f"chain_exchange_protocol: {FIL_CHAIN_EXCHANGE_PROTOCOL}")
        print(f"blocks_topic: {blocks_topic(network_name)}")
        print(f"messages_topic: {messages_topic(network_name)}")
        print(f"dht_protocol: {dht_protocol_name(network_name)}")
        print(f"score_mode: {args.score_mode}")
        print(f"publish_threshold: {score_params.publish_threshold}")
        print(f"gossip_threshold: {score_params.gossip_threshold}")
        print(f"graylist_threshold: {score_params.graylist_threshold}")
        print(f"accept_px_threshold: {score_params.accept_px_threshold}")
        print(f"degree: {gossipsub.degree}")
        print(f"degree_low: {gossipsub.degree_low}")
        print(f"degree_high: {gossipsub.degree_high}")
        print(f"gossip_history: {gossipsub.mcache.history_size}")
        print(f"direct_connect_initial_delay: {gossipsub.direct_connect_initial_delay}")
        print(f"do_px: {gossipsub.do_px}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filecoin-dx",
        description="Filecoin developer tooling for py-libp2p",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    topics_parser = subparsers.add_parser(
        "topics", help="print Filecoin topic and DHT protocol strings"
    )
    topics_parser.add_argument(
        "--network",
        choices=("mainnet", "calibnet"),
        default="mainnet",
        help="Filecoin network alias",
    )
    topics_parser.add_argument(
        "--network-name",
        type=str,
        default=None,
        help="explicit network name suffix (overrides alias mapping)",
    )
    topics_parser.add_argument(
        "--json",
        action="store_true",
        help="output JSON",
    )
    topics_parser.set_defaults(handler=_cmd_topics)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="print canonical or runtime-compatible bootstrap peers"
    )
    bootstrap_parser.add_argument(
        "--network",
        choices=("mainnet", "calibnet"),
        default="mainnet",
        help="Filecoin network alias",
    )
    mode_group = bootstrap_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--canonical",
        action="store_true",
        help="show canonical bootstrap list",
    )
    mode_group.add_argument(
        "--runtime",
        action="store_true",
        help="show runtime-compatible bootstrap list",
    )
    bootstrap_parser.add_argument(
        "--resolve-dns",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="resolve dns bootstrap addresses to /ip4/.../tcp/... entries",
    )
    bootstrap_parser.add_argument(
        "--include-quic",
        action="store_true",
        help="include QUIC/webtransport entries in runtime output",
    )
    bootstrap_parser.add_argument(
        "--json",
        action="store_true",
        help="output JSON",
    )
    bootstrap_parser.set_defaults(handler=_cmd_bootstrap)

    preset_parser = subparsers.add_parser(
        "preset", help="dump effective Filecoin pubsub preset values"
    )
    preset_parser.add_argument(
        "--network",
        choices=("mainnet", "calibnet"),
        default="mainnet",
        help="Filecoin network alias",
    )
    preset_parser.add_argument(
        "--network-name",
        type=str,
        default=None,
        help="explicit network name suffix (overrides alias mapping)",
    )
    preset_parser.add_argument(
        "--score-mode",
        default="thresholds_only",
        help="score mode to build",
    )
    preset_parser.add_argument(
        "--bootstrapper",
        action="store_true",
        help="build bootstrapper-flavored gossipsub preset",
    )
    preset_parser.add_argument(
        "--json",
        action="store_true",
        help="output JSON",
    )
    preset_parser.set_defaults(handler=_cmd_preset)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    return args.handler(args)

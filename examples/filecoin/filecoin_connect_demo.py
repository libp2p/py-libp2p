from __future__ import annotations

import argparse
import json
import logging
from typing import Any

import multiaddr
import trio

from libp2p import new_host
from libp2p.filecoin import get_network_preset, get_runtime_bootstrap_addresses
from libp2p.filecoin.interop import (
    classify_probe_result,
    extract_connection_metadata,
)
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.utils.address_validation import find_free_port

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_result(
    network_alias: str,
    network_name: str,
    attempted: int,
    connected: bool,
    address: str | None,
    peer_id: str | None,
    connection: dict[str, Any] | None,
    interop: dict[str, Any],
    error: str | None,
) -> dict[str, Any]:
    return {
        "network_alias": network_alias,
        "network_name": network_name,
        "attempted": attempted,
        "connected": connected,
        "address": address,
        "peer_id": peer_id,
        "connection": connection,
        "interop": interop,
        "error": error,
    }


async def run(
    network: str,
    peer: str | None,
    resolve_dns: bool,
    timeout: float,
    as_json: bool,
) -> int:
    preset = get_network_preset(network)
    network_name = preset.genesis_network_name

    candidates = (
        [peer]
        if peer
        else get_runtime_bootstrap_addresses(network, resolve_dns=resolve_dns)
    )
    workflow = "explicit_peer" if peer else "runtime_bootstrap_smoke"
    case = (
        "explicit_filecoin_peer_connect"
        if peer
        else "public_filecoin_bootstrap_connect"
    )

    if not candidates:
        interop = {
            "case": case,
            "workflow": workflow,
            "result": "fail",
            "failure_mode": "no candidate peer addresses available",
        }
        result = _build_result(
            network_alias=network,
            network_name=network_name,
            attempted=0,
            connected=False,
            address=None,
            peer_id=None,
            connection=None,
            interop=interop,
            error="no candidate peer addresses available",
        )
        if as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            logger.error(result["error"])
        return 1

    listen_port = find_free_port()
    listen_addrs = [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{listen_port}")]
    host = new_host(listen_addrs=listen_addrs)

    selected_addr: str | None = None
    selected_peer_id: str | None = None
    selected_connection: dict[str, Any] | None = None
    last_error: str | None = None

    async with host.run(listen_addrs=listen_addrs):
        for addr in candidates:
            try:
                info = info_from_p2p_addr(multiaddr.Multiaddr(addr))
                with trio.fail_after(timeout):
                    await host.connect(info)
                selected_addr = addr
                selected_peer_id = str(info.peer_id)
                selected_connection = extract_connection_metadata(host, info.peer_id)
                break
            except Exception as exc:
                last_error = str(exc)

    connected = selected_addr is not None
    interop = {
        "case": case,
        "workflow": workflow,
        "result": classify_probe_result(
            connected=connected,
            metadata_captured=selected_connection is not None,
            checks_satisfied=connected,
        ),
        "failure_mode": None if connected else last_error,
    }
    result = _build_result(
        network_alias=network,
        network_name=network_name,
        attempted=len(candidates),
        connected=connected,
        address=selected_addr,
        peer_id=selected_peer_id,
        connection=selected_connection,
        interop=interop,
        error=None if connected else last_error,
    )

    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        logger.info("network alias: %s", result["network_alias"])
        logger.info("network name: %s", result["network_name"])
        logger.info("attempted peers: %s", result["attempted"])
        if connected:
            logger.info("connected peer: %s", result["peer_id"])
            logger.info("connected address: %s", result["address"])
            if result["connection"] is not None:
                logger.info(
                    "transport/security/muxer: %s / %s / %s",
                    result["connection"]["transport_family"],
                    result["connection"]["security_protocol"],
                    result["connection"]["muxer_protocol"],
                )
        else:
            logger.error("connect failed: %s", result["error"])

    return 0 if connected else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connect to a Filecoin peer via py-libp2p runtime bootstrap set.",
    )
    parser.add_argument(
        "--network",
        choices=("mainnet", "calibnet"),
        default="mainnet",
        help="Filecoin network alias.",
    )
    parser.add_argument(
        "--peer",
        type=str,
        default=None,
        help="Explicit /.../p2p/<peer-id> multiaddr to dial.",
    )
    parser.add_argument(
        "--resolve-dns",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resolve DNS bootstrap entries for runtime dialing.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-peer dial timeout in seconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print deterministic JSON output.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(
            trio.run(
                run,
                args.network,
                args.peer,
                args.resolve_dns,
                args.timeout,
                args.json,
            )
        )
    except KeyboardInterrupt:
        logger.info("interrupted")
        raise SystemExit(130)


if __name__ == "__main__":
    main()

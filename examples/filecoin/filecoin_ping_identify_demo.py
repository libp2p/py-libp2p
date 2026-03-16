from __future__ import annotations

import argparse
import json
import logging
from statistics import mean
from typing import Any

import multiaddr
import trio

from libp2p import new_host
from libp2p.filecoin import (
    FIL_CHAIN_EXCHANGE_PROTOCOL,
    FIL_HELLO_PROTOCOL,
    get_network_preset,
    get_runtime_bootstrap_addresses,
)
from libp2p.filecoin.interop import (
    classify_probe_result,
    extract_connection_metadata,
)
from libp2p.host.ping import PingService
from libp2p.identity.identify.identify import (
    ID as IDENTIFY_PROTOCOL_ID,
    parse_identify_response,
)
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.utils.address_validation import find_free_port
from libp2p.utils.varint import read_length_prefixed_protobuf

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_result(
    network_alias: str,
    network_name: str,
    connected: bool,
    address: str | None,
    peer_id: str | None,
    connection: dict[str, Any] | None,
    identify: dict[str, Any] | None,
    ping: dict[str, Any] | None,
    interop: dict[str, Any],
    error: str | None,
) -> dict[str, Any]:
    return {
        "network_alias": network_alias,
        "network_name": network_name,
        "connected": connected,
        "address": address,
        "peer_id": peer_id,
        "connection": connection,
        "identify": identify,
        "ping": ping,
        "interop": interop,
        "error": error,
    }


async def _run_identify(host: Any, peer_id: Any) -> dict[str, Any]:
    stream = await host.new_stream(peer_id, [IDENTIFY_PROTOCOL_ID])
    raw_response = await read_length_prefixed_protobuf(stream, use_varint_format=True)
    await stream.close()

    identify_msg = parse_identify_response(raw_response)
    protocols = list(identify_msg.protocols)
    advertised_filecoin_protocols = [
        protocol for protocol in protocols if protocol.startswith("/fil/")
    ]

    return {
        "agent_version": identify_msg.agent_version,
        "protocol_version": identify_msg.protocol_version,
        "protocol_count": len(protocols),
        "advertised_filecoin_protocols": advertised_filecoin_protocols,
        "supports_filecoin_hello": str(FIL_HELLO_PROTOCOL) in protocols,
        "supports_filecoin_chain_exchange": str(FIL_CHAIN_EXCHANGE_PROTOCOL)
        in protocols,
    }


async def _run_ping(host: Any, peer_id: Any, ping_count: int) -> dict[str, Any]:
    ping_service = PingService(host)
    rtts = await ping_service.ping(peer_id, ping_amt=ping_count)
    return {
        "count": ping_count,
        "rtts_us": rtts,
        "avg_rtt_us": mean(rtts) if rtts else None,
    }


async def run(
    network: str,
    peer: str | None,
    resolve_dns: bool,
    timeout: float,
    ping_count: int,
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
        "explicit_filecoin_ping_identify" if peer else "public_filecoin_ping_identify"
    )

    if not candidates:
        result = _build_result(
            network_alias=network,
            network_name=network_name,
            connected=False,
            address=None,
            peer_id=None,
            connection=None,
            identify=None,
            ping=None,
            interop={
                "case": case,
                "workflow": workflow,
                "result": "fail",
                "failure_mode": "no candidate peer addresses available",
            },
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
    selected_info = None
    selected_connection: dict[str, Any] | None = None
    last_error: str | None = None
    identify_payload: dict[str, Any] | None = None
    ping_payload: dict[str, Any] | None = None

    async with host.run(listen_addrs=listen_addrs):
        for addr in candidates:
            try:
                info = info_from_p2p_addr(multiaddr.Multiaddr(addr))
                with trio.fail_after(timeout):
                    await host.connect(info)
                selected_addr = addr
                selected_info = info
                selected_connection = extract_connection_metadata(host, info.peer_id)
                break
            except Exception as exc:
                last_error = str(exc)

        if selected_info is not None:
            try:
                identify_payload = await _run_identify(host, selected_info.peer_id)
                ping_payload = await _run_ping(host, selected_info.peer_id, ping_count)
            except Exception as exc:
                last_error = str(exc)

    connected = selected_addr is not None
    checks_satisfied = identify_payload is not None and ping_payload is not None
    interop = {
        "case": case,
        "workflow": workflow,
        "result": classify_probe_result(
            connected=connected,
            metadata_captured=selected_connection is not None,
            checks_satisfied=checks_satisfied,
        ),
        "failure_mode": None if checks_satisfied else last_error,
    }
    result = _build_result(
        network_alias=network,
        network_name=network_name,
        connected=connected and checks_satisfied,
        address=selected_addr,
        peer_id=str(selected_info.peer_id) if selected_info else None,
        connection=selected_connection,
        identify=identify_payload,
        ping=ping_payload,
        interop=interop,
        error=last_error,
    )

    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        logger.info("network alias: %s", result["network_alias"])
        logger.info("network name: %s", result["network_name"])
        logger.info("peer: %s", result["peer_id"])
        logger.info("address: %s", result["address"])
        if result["connection"] is not None:
            logger.info(
                "transport/security/muxer: %s / %s / %s",
                result["connection"]["transport_family"],
                result["connection"]["security_protocol"],
                result["connection"]["muxer_protocol"],
            )
        if result["identify"] is not None:
            logger.info("agent version: %s", result["identify"]["agent_version"])
            logger.info(
                "supports /fil/hello/1.0.0: %s",
                result["identify"]["supports_filecoin_hello"],
            )
            logger.info(
                "supports /fil/chain/xchg/0.0.1: %s",
                result["identify"]["supports_filecoin_chain_exchange"],
            )
        if result["ping"] is not None:
            logger.info("ping avg RTT (us): %s", result["ping"]["avg_rtt_us"])
        if result["error"] is not None:
            logger.error("diagnostic error: %s", result["error"])

    return 0 if result["connected"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dial a Filecoin peer and run identify + ping diagnostics.",
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
        "--ping-count",
        type=int,
        default=3,
        help="Number of ping probes to run after dialing.",
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
                args.ping_count,
                args.json,
            )
        )
    except KeyboardInterrupt:
        logger.info("interrupted")
        raise SystemExit(130)


if __name__ == "__main__":
    main()

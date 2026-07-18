from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Any

import multiaddr
import trio

from libp2p import new_host
from libp2p.filecoin import (
    FIL_CHAIN_EXCHANGE_PROTOCOL,
    FIL_HELLO_PROTOCOL,
    blocks_topic,
    build_filecoin_gossipsub,
    build_filecoin_pubsub,
    dht_protocol_name,
    get_network_preset,
    get_runtime_bootstrap_addresses,
    messages_topic,
)
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.anyio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class ObserverState:
    stop_event: trio.Event
    message_count: int
    max_messages: int | None
    lock: trio.Lock

    async def on_message(self) -> int:
        async with self.lock:
            self.message_count += 1
            if (
                self.max_messages is not None
                and self.max_messages > 0
                and self.message_count >= self.max_messages
            ):
                self.stop_event.set()
            return self.message_count


def _selected_topics(topic_mode: str, network_name: str) -> list[str]:
    if topic_mode == "blocks":
        return [blocks_topic(network_name)]
    if topic_mode == "messages":
        return [messages_topic(network_name)]
    return [blocks_topic(network_name), messages_topic(network_name)]


def _build_snapshot(
    network_alias: str,
    network_name: str,
    bootstrap_addrs: Sequence[str],
    listen_port: int,
    topics: Sequence[str],
    max_messages: int | None,
) -> dict[str, Any]:
    return {
        "network_alias": network_alias,
        "network_name": network_name,
        "protocols": {
            "hello": str(FIL_HELLO_PROTOCOL),
            "chain_exchange": str(FIL_CHAIN_EXCHANGE_PROTOCOL),
            "dht": str(dht_protocol_name(network_name)),
        },
        "topics": {
            "blocks": blocks_topic(network_name),
            "messages": messages_topic(network_name),
            "selected": list(topics),
        },
        "mode": "read_only_observer",
        "bootstrap_count": len(bootstrap_addrs),
        "bootstrap_addresses": list(bootstrap_addrs),
        "listen_addr": f"/ip4/0.0.0.0/tcp/{listen_port}",
        "max_messages": max_messages,
    }


async def _observe_topic(
    topic: str,
    subscription: Any,
    state: ObserverState,
) -> None:
    while not state.stop_event.is_set():
        try:
            message = await subscription.get()
        except Exception as exc:
            logger.warning("subscription error on %s: %s", topic, exc)
            return

        source = "unknown"
        if message.from_id:
            source = ID(message.from_id).to_base58()

        ordinal = await state.on_message()
        payload_size = len(message.data) if message.data is not None else 0
        observed_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "observed message #%d topic=%s source=%s payload_bytes=%d ts=%s",
            ordinal,
            topic,
            source,
            payload_size,
            observed_at,
        )


async def _connect_bootstrap_peers(
    host: Any,
    addrs: Sequence[str],
    timeout: float = 8.0,
    max_success: int = 3,
) -> int:
    connected = 0
    for addr in addrs:
        if connected >= max_success:
            break
        try:
            info = info_from_p2p_addr(multiaddr.Multiaddr(addr))
        except Exception as exc:
            logger.debug("invalid bootstrap address %s: %s", addr, exc)
            continue

        try:
            with trio.move_on_after(timeout) as scope:
                await host.connect(info)
            if scope.cancelled_caught:
                logger.debug("timeout connecting bootstrap peer %s", info.peer_id)
                continue
            connected += 1
            logger.info("connected bootstrap peer: %s", info.peer_id)
        except Exception as exc:
            logger.debug("failed bootstrap connect %s: %s", info.peer_id, exc)
    return connected


async def run(
    network: str,
    resolve_dns: bool,
    include_quic: bool,
    run_seconds: float,
    max_messages: int | None,
    topic_mode: str,
    as_json: bool,
) -> int:
    preset = get_network_preset(network)
    network_name = preset.genesis_network_name
    topics = _selected_topics(topic_mode, network_name)

    runtime_bootstrap = get_runtime_bootstrap_addresses(
        network,
        resolve_dns=resolve_dns,
        include_quic=include_quic,
    )

    listen_port = find_free_port()
    listen_addrs = [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{listen_port}")]
    # Delay bootstrap dials until pubsub services are running to avoid races
    # where inbound streams are handled before Pubsub manager initialization.
    host = new_host(listen_addrs=listen_addrs)

    gossipsub = build_filecoin_gossipsub(network_name=network_name)
    pubsub = build_filecoin_pubsub(
        host=host,
        gossipsub=gossipsub,
        network_name=network_name,
    )

    snapshot = _build_snapshot(
        network_alias=network,
        network_name=network_name,
        bootstrap_addrs=runtime_bootstrap,
        listen_port=listen_port,
        topics=topics,
        max_messages=max_messages,
    )

    if as_json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        logger.info("network alias: %s", snapshot["network_alias"])
        logger.info("network name: %s", snapshot["network_name"])
        logger.info("hello protocol: %s", snapshot["protocols"]["hello"])
        logger.info(
            "chain exchange protocol: %s",
            snapshot["protocols"]["chain_exchange"],
        )
        logger.info("dht protocol: %s", snapshot["protocols"]["dht"])
        logger.info("selected topics: %s", ", ".join(topics))
        logger.info("runtime bootstrap peers: %d", snapshot["bootstrap_count"])
        logger.info("observer mode: read-only (publishing disabled)")
        for addr in runtime_bootstrap[:5]:
            logger.info("bootstrap: %s", addr)

    state = ObserverState(
        stop_event=trio.Event(),
        message_count=0,
        max_messages=max_messages,
        lock=trio.Lock(),
    )

    async with host.run(listen_addrs=listen_addrs):
        async with background_trio_service(pubsub):
            async with background_trio_service(gossipsub):
                await pubsub.wait_until_ready()
                connected_bootstrap = await _connect_bootstrap_peers(
                    host,
                    runtime_bootstrap,
                    timeout=8.0,
                    max_success=3,
                )
                logger.info("connected bootstrap peers: %d", connected_bootstrap)

                subscriptions = {}
                for topic in topics:
                    subscriptions[topic] = await pubsub.subscribe(topic)
                    logger.info("subscribed to %s", topic)

                async with trio.open_nursery() as nursery:
                    for topic, subscription in subscriptions.items():
                        nursery.start_soon(_observe_topic, topic, subscription, state)

                    if run_seconds > 0:
                        with trio.move_on_after(run_seconds):
                            await state.stop_event.wait()
                        state.stop_event.set()
                    else:
                        await state.stop_event.wait()
                    nursery.cancel_scope.cancel()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filecoin pubsub read-only observer using libp2p.filecoin presets.",
    )
    parser.add_argument(
        "--network",
        choices=("mainnet", "calibnet"),
        default="mainnet",
        help="Filecoin network alias.",
    )
    parser.add_argument(
        "--resolve-dns",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resolve dns bootstrap entries to /ip4/.../tcp/... addresses.",
    )
    parser.add_argument(
        "--include-quic",
        action="store_true",
        help="Include QUIC and WebTransport bootstrap entries.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=20.0,
        help="How long to keep the observer running. Use 0 for indefinite run.",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Stop after this many observed messages across selected topics.",
    )
    parser.add_argument(
        "--topic",
        choices=("blocks", "messages", "both"),
        default="both",
        help="Which Filecoin gossip topics to observe.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print configuration snapshot as JSON before starting.",
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
                args.resolve_dns,
                args.include_quic,
                args.seconds,
                args.max_messages,
                args.topic,
                args.json,
            )
        )
    except KeyboardInterrupt:
        logger.info("interrupted")
        raise SystemExit(130)


if __name__ == "__main__":
    main()

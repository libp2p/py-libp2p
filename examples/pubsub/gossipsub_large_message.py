import argparse
import logging
import struct
import time

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.pubsub.pubsub import (
    Pubsub,
)
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.tools.anyio_service import (
    background_trio_service,
)
from libp2p.utils.address_validation import (
    find_free_port,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("gossipsub-large-message-demo")

GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
TOPIC = "gossipsub-large-message"
PAYLOAD_SIZE_BYTES = 500 * 1024
TIMESTAMP_BYTES = 8


def build_large_payload() -> bytes:
    sent_at = time.time()
    body_size = PAYLOAD_SIZE_BYTES - TIMESTAMP_BYTES
    if body_size <= 0:
        raise ValueError("PAYLOAD_SIZE_BYTES must be larger than 8 bytes")
    body = b"x" * body_size
    return struct.pack("!d", sent_at) + body


def extract_timestamp(payload: bytes) -> float:
    if len(payload) < TIMESTAMP_BYTES:
        raise ValueError("payload does not include timestamp header")
    return struct.unpack("!d", payload[:TIMESTAMP_BYTES])[0]


async def create_pubsub_stack() -> tuple:
    host = new_host(
        key_pair=create_new_key_pair(),
        muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
    )
    gossipsub = GossipSub(
        protocols=[GOSSIPSUB_PROTOCOL_ID],
        degree=3,
        degree_low=2,
        degree_high=4,
        direct_peers=None,
        time_to_live=60,
        gossip_window=2,
        gossip_history=5,
        heartbeat_initial_delay=2.0,
        heartbeat_interval=5,
    )
    pubsub = Pubsub(host, gossipsub)
    return host, gossipsub, pubsub


async def run_receiver(topic: str, port: int | None) -> None:
    from libp2p.utils.address_validation import (
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if port is None or port == 0:
        port = find_free_port()
        logger.info("Using random available port: %s", port)

    host, gossipsub, pubsub = await create_pubsub_stack()
    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs=listen_addrs):
        async with background_trio_service(pubsub):
            async with background_trio_service(gossipsub):
                await pubsub.wait_until_ready()
                subscription = await pubsub.subscribe(topic)

                optimal_addr = get_optimal_binding_address(port)
                receiver_addr = f"{optimal_addr}/p2p/{host.get_id().to_string()}"

                logger.info("Receiver ready with peer ID: %s", host.get_id())
                logger.info("Topic: %s", topic)
                logger.info("Run this in a second terminal to send 500KB:")
                logger.info("gossipsub-large-message-demo -d %s -t %s", receiver_addr, topic)

                logger.info("Waiting for one large message...")
                message = await subscription.get()
                received_at = time.time()
                sent_at = extract_timestamp(message.data)
                elapsed_ms = (received_at - sent_at) * 1000
                sender_peer_id = ID(message.from_id).to_base58()

                logger.info(
                    "Received payload: %d bytes on topic '%s' from %s",
                    len(message.data),
                    topic,
                    sender_peer_id,
                )
                logger.info("End-to-end elapsed time: %.2f ms", elapsed_ms)


async def run_sender(topic: str, destination: str, port: int | None) -> None:
    from libp2p.utils.address_validation import (
        get_available_interfaces,
    )

    if port is None or port == 0:
        port = find_free_port()

    host, gossipsub, pubsub = await create_pubsub_stack()
    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs=listen_addrs):
        async with background_trio_service(pubsub):
            async with background_trio_service(gossipsub):
                await pubsub.wait_until_ready()

                maddr = multiaddr.Multiaddr(destination)
                info = info_from_p2p_addr(maddr)
                await host.connect(info)

                await pubsub.wait_for_peer(info.peer_id)
                await pubsub.wait_for_subscription(info.peer_id, topic)

                payload = build_large_payload()
                logger.info(
                    "Publishing %d-byte payload to topic '%s'...",
                    len(payload),
                    topic,
                )
                publish_start = time.perf_counter()
                await pubsub.publish(topic, payload)
                publish_ms = (time.perf_counter() - publish_start) * 1000
                logger.info("Publish completed in %.2f ms", publish_ms)


async def run(topic: str, destination: str | None, port: int | None) -> None:
    if destination:
        await run_sender(topic, destination, port)
    else:
        await run_receiver(topic, port)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "GossipSub large-message demo. Start receiver first, then run sender "
            "with -d to publish one 500KB payload and print timing on receiver."
        )
    )
    parser.add_argument(
        "-t",
        "--topic",
        type=str,
        default=TOPIC,
        help="Topic name to use (default: gossipsub-large-message)",
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        default=None,
        help="Receiver multiaddr with /p2p/<peer_id> (sender mode)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help="Local listen port (default: random free port)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.destination:
        logger.info("Running sender mode")
    else:
        logger.info("Running receiver mode")

    try:
        trio.run(run, *(args.topic, args.destination, args.port))
    except KeyboardInterrupt:
        logger.info("Application terminated by user")


if __name__ == "__main__":
    main()

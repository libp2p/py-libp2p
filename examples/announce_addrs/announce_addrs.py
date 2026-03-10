"""
Announce Addresses Example for py-libp2p

Demonstrates how to use announce addresses so that a node behind NAT
or a reverse proxy (e.g. ngrok) advertises its publicly reachable
address instead of its local listen address.

Node A (listener):
    python announce_addrs.py --listen-port 9001 \
        --announce /dns4/example.ngrok-free.app/tcp/9001 /ip4/1.2.3.4/tcp/4001

Node B (dialer):
    python announce_addrs.py --listen-port 9002 \
        --dial /dns4/example.ngrok-free.app/tcp/9001/p2p/<PEER_ID_OF_A>
"""

import argparse
import logging
import secrets

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("announce_addrs_example")

# Silence noisy libraries
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)
logger.setLevel(logging.INFO)


async def run_listener(port: int, announce_addrs: list[str]) -> None:
    """Start a node that listens locally and announces external addresses."""
    key_pair = create_new_key_pair(secrets.token_bytes(32))

    listen_addrs = [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]

    parsed_announce = [multiaddr.Multiaddr(a) for a in announce_addrs]

    host = new_host(key_pair=key_pair, announce_addrs=parsed_announce)

    async with host.run(listen_addrs=listen_addrs):
        peer_id = host.get_id().to_string()

        logger.info("Node started")
        logger.info(f"Peer ID: {peer_id}")

        logger.info("Transport (local) addresses:")
        for addr in host.get_transport_addrs():
            logger.info(f"  {addr}")

        logger.info("Announced (public) addresses:")
        for addr in host.get_addrs():
            logger.info(f"  {addr}")

        print(f"\nPeer ID: {peer_id}")
        print("\nTo connect from another node, run:")
        for addr in host.get_addrs():
            print(f"  python announce_addrs.py --listen-port 9002 --dial {addr}")

        print("\nPress Ctrl+C to exit.")
        await trio.sleep_forever()


async def run_dialer(port: int, dial_addr: str) -> None:
    """Start a node and connect to a remote peer."""
    key_pair = create_new_key_pair(secrets.token_bytes(32))

    listen_addrs = [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]

    host = new_host(key_pair=key_pair)

    async with host.run(listen_addrs=listen_addrs):
        logger.info(f"Dialer started, peer ID: {host.get_id().to_string()}")

        ma = multiaddr.Multiaddr(dial_addr)
        peer_info = info_from_p2p_addr(ma)

        logger.info(f"Connecting to {peer_info.peer_id}...")
        await host.connect(peer_info)
        logger.info(f"Successfully connected to {peer_info.peer_id}")

        print(f"\nConnected to peer: {peer_info.peer_id}")
        print("Press Ctrl+C to exit.")
        await trio.sleep_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Announce Addresses Example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=9001,
        help="Local TCP port to listen on (default: 9001)",
    )
    parser.add_argument(
        "--announce",
        nargs="+",
        help="Announce addresses (e.g. /dns4/example.ngrok-free.app/tcp/443)",
    )
    parser.add_argument(
        "--dial",
        type=str,
        help="Full multiaddr of remote peer to connect (must include /p2p/<peerID>)",
    )

    args = parser.parse_args()

    if args.dial:
        trio.run(run_dialer, args.listen_port, args.dial)
    elif args.announce:
        trio.run(run_listener, args.listen_port, args.announce)
    else:
        parser.error("Provide --announce to listen, or --dial to connect to a peer.")


if __name__ == "__main__":
    main()

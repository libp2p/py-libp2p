"""
Announce Addresses Example for py-libp2p

Demonstrates how to advertise publicly reachable addresses when a node is
behind NAT or a reverse proxy (e.g. ngrok), including the go-libp2p parity
knobs from issue #1311 / #1478:

* static ``--announce`` / ``announce_addrs``
* callable ``addrs_factory`` via ``--factory-extra`` (compose live candidates
  + extra multiaddrs)
* ``--disable-identify-address-discovery`` (opt out of Identify observations)

Static announce and factory mode are mutually exclusive (same as the API).

Node A (listener, static announce):
    python announce_addrs.py --listen-port 9001 \
        --announce /dns4/example.ngrok-free.app/tcp/9001 /ip4/1.2.3.4/tcp/4001

Node A (listener, static announce + disable Identify discovery):
    python announce_addrs.py --listen-port 9001 \
        --announce /ip4/1.2.3.4/tcp/4001 \
        --disable-identify-address-discovery

Node A (listener, addrs_factory compose mode):
    python announce_addrs.py --listen-port 9001 \
        --factory-extra /dns4/example.ngrok-free.app/tcp/9001

Node B (dialer):
    python announce_addrs.py --listen-port 9002 \
        --dial /dns4/example.ngrok-free.app/tcp/9001/p2p/<PEER_ID_OF_A>
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
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


def _make_compose_factory(
    extra_addrs: Sequence[multiaddr.Multiaddr],
) -> Callable[[list[multiaddr.Multiaddr]], list[multiaddr.Multiaddr]]:
    """Build an AddrsFactory that keeps live candidates and appends extras."""
    extras = list(extra_addrs)

    def factory(candidates: list[multiaddr.Multiaddr]) -> list[multiaddr.Multiaddr]:
        seen = {str(a) for a in candidates}
        result = list(candidates)
        for addr in extras:
            key = str(addr)
            if key not in seen:
                seen.add(key)
                result.append(addr)
        return result

    return factory


async def run_listener(
    port: int,
    announce_addrs: list[str] | None,
    factory_extra: list[str] | None,
    disable_identify_address_discovery: bool = False,
) -> None:
    """Start a node that listens locally and advertises configured addresses."""
    key_pair = create_new_key_pair(secrets.token_bytes(32))
    listen_addrs = [multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]

    host_kwargs: dict = {
        "key_pair": key_pair,
        "disable_identify_address_discovery": disable_identify_address_discovery,
    }
    if announce_addrs is not None:
        host_kwargs["announce_addrs"] = [multiaddr.Multiaddr(a) for a in announce_addrs]
    elif factory_extra is not None:
        extras = [multiaddr.Multiaddr(a) for a in factory_extra]
        host_kwargs["addrs_factory"] = _make_compose_factory(extras)

    host = new_host(**host_kwargs)

    async with host.run(listen_addrs=listen_addrs):
        peer_id = host.get_id().to_string()

        logger.info("Node started")
        logger.info(f"Peer ID: {peer_id}")
        if disable_identify_address_discovery:
            logger.info("Identify address discovery: disabled")
        if announce_addrs is not None:
            logger.info("Mode: static announce_addrs")
        elif factory_extra is not None:
            logger.info("Mode: addrs_factory (compose live candidates + extras)")

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
        description=(
            "Announce Addresses Example — static announce_addrs, "
            "addrs_factory compose mode, and optional Identify discovery opt-out."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  Static announce:\n"
            "    %(prog)s --listen-port 9001 "
            "--announce /dns4/example.ngrok-free.app/tcp/9001\n"
            "  Static announce + disable Identify discovery:\n"
            "    %(prog)s --listen-port 9001 --announce /ip4/1.2.3.4/tcp/4001 "
            "--disable-identify-address-discovery\n"
            "  Factory compose (live candidates + extras):\n"
            "    %(prog)s --listen-port 9001 "
            "--factory-extra /dns4/example.ngrok-free.app/tcp/9001\n"
            "  Dialer:\n"
            "    %(prog)s --listen-port 9002 "
            "--dial /dns4/example.ngrok-free.app/tcp/9001/p2p/<PEER_ID>\n"
        ),
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
        help=(
            "Static announce addresses "
            "(e.g. /dns4/example.ngrok-free.app/tcp/443). "
            "Mutually exclusive with --factory-extra."
        ),
    )
    parser.add_argument(
        "--factory-extra",
        nargs="+",
        metavar="MULTIADDR",
        help=(
            "Use addrs_factory: advertise live candidates "
            "(listen + confirmed observed, unless discovery is disabled) "
            "plus these extra multiaddrs. Mutually exclusive with --announce."
        ),
    )
    parser.add_argument(
        "--disable-identify-address-discovery",
        action="store_true",
        help=(
            "Do not record Identify observed addresses for local discovery "
            "(go-libp2p DisableIdentifyAddressDiscovery). Identify still runs "
            "for peer metadata. Useful with --announce when public addresses "
            "are known upfront."
        ),
    )
    parser.add_argument(
        "--dial",
        type=str,
        help="Full multiaddr of remote peer to connect (must include /p2p/<peerID>)",
    )

    args = parser.parse_args()

    if args.dial:
        trio.run(run_dialer, args.listen_port, args.dial)
        return

    if args.announce and args.factory_extra:
        parser.error(
            "cannot combine --announce and --factory-extra "
            "(same mutual exclusion as announce_addrs vs addrs_factory)"
        )

    if not args.announce and not args.factory_extra:
        parser.error(
            "Provide --announce or --factory-extra to listen, "
            "or --dial to connect to a peer."
        )

    trio.run(
        run_listener,
        args.listen_port,
        args.announce,
        args.factory_extra,
        args.disable_identify_address_discovery,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import hashlib
import logging
from pathlib import Path

import trio
from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.utils.address_validation import find_free_port, get_available_interfaces
from libp2p.bitswap.cid import format_cid_for_display

from libp2p import new_host
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.security.secio.transport import Transport as SecioTransport
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.crypto.keys import KeyPair
from py_ipfs_lite.config import Config, AddParams, CLIConfig
from py_ipfs_lite.parser import get_parser
from libp2p.bitswap import BitswapClient, MemoryBlockStore
from libp2p.bitswap.dag import MerkleDag
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.bitswap.cid import parse_cid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)

# Silence verbose loggers
logging.getLogger("multiaddr.transforms").setLevel(logging.WARNING)
logging.getLogger("multiaddr.codecs.cid").setLevel(logging.WARNING)
logging.getLogger("libp2p.tools.anyio_service").setLevel(logging.WARNING)

logger = logging.getLogger("py_ipfs_lite.main")


def format_size(size_bytes: int) -> str:
    """Format size in human-readable form."""
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def create_host_and_routing(listen_addrs: list, host_key: KeyPair | None = None):
    maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in listen_addrs]
    host_key_pair = host_key if host_key else create_new_key_pair()

    noise_key_pair = create_new_x25519_key_pair()
    sec_opt = {
        "/noise": NoiseTransport(
            host_key_pair, noise_privkey=noise_key_pair.private_key
        ),
        "/secio/1.0.0": SecioTransport(host_key_pair),
    }

    host = new_host(key_pair=host_key_pair, listen_addrs=maddrs, sec_opt=sec_opt)
    routing = KadDHT(host=host, mode=DHTMode.SERVER)
    return host, routing


async def run_daemon(port: int, seed: str | None, config: Config):
    """Run the IPFS Lite daemon (provider mode)."""
    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    key_pair = None
    if seed:
        seed_bytes = hashlib.sha256(seed.encode()).digest()
        key_pair = create_new_key_pair(seed=seed_bytes)
        logger.info("Using deterministic peer ID from seed")

    logger.info("Starting py-ipfs-lite daemon...")
    host, routing = await create_host_and_routing(
        host_key=key_pair,
        listen_addrs=listen_addrs,
    )

    async with host.run(listen_addrs=listen_addrs):
        bitswap = BitswapClient(host, MemoryBlockStore())
        await bitswap.start()
        dag = MerkleDag(bitswap)

        from py_ipfs_lite.api import start_api_server

        async with trio.open_nursery() as nursery:
            nursery.start_soon(start_api_server, dag, host)

            logger.info(f"Daemon Peer ID: {host.get_id()}")
            addrs = host.get_addrs()
            logger.info(f"Listening on {len(addrs)} address(es):")
            for addr in addrs:
                logger.info(f"  {addr}")

            try:
                logger.info(
                    "Daemon is running and API is listening on 127.0.0.1:5002. Press Ctrl+C to stop..."
                )
                await trio.sleep_forever()
            except KeyboardInterrupt:
                logger.info("\nShutting down...")
                nursery.cancel_scope.cancel()

        await bitswap.stop()


async def run_add(
    file_path: str, port: int, seed: str | None, config: Config, add_params: AddParams
):
    """Add a file to the IPFS Lite network."""
    from py_ipfs_lite.api import api_client_send
    import os

    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return

    abs_path = os.path.abspath(file_path)
    req = {"cmd": "add", "file": abs_path}
    logger.info(f"Sending file {file_path} to daemon...")
    resp = await api_client_send(req)
    if resp.get("status") == "ok":
        logger.info(f"Added file successfully! CID: {resp.get('cid')}")
        logger.info(f"Provider Peer ID: {resp.get('peer_id')}")
        logger.info("Provide the following address to peers:")
        for addr in resp.get("addrs", []):
            logger.info(f"  {addr}")
    else:
        logger.error(f"Error: {resp.get('error')}")


async def run_get(
    cid_str: str,
    provider_addr: str,
    out_file: str | None,
    port: int,
    seed: str | None,
    config: Config,
):
    """Fetch a file by CID."""
    from py_ipfs_lite.api import api_client_send
    import os

    req = {"cmd": "get", "cid": cid_str}
    if provider_addr:
        req["provider"] = provider_addr
    if out_file:
        req["out"] = os.path.abspath(out_file)

    logger.info(f"Requesting daemon to fetch CID {cid_str}...")
    resp = await api_client_send(req)
    if resp.get("status") == "ok":
        logger.info(resp.get("message"))
        if "content" in resp:
            print(resp["content"])
    else:
        logger.error(f"Error: {resp.get('error')}")


def main():
    parser = get_parser()
    parsed_args = parser.parse_args()

    if parsed_args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if parsed_args.command == "daemon":
        config = Config(
            offline=parsed_args.offline,
            reprovide_interval_seconds=parsed_args.reprovide_interval_seconds,
        )
        trio.run(run_daemon, parsed_args.port, parsed_args.seed, config)

    elif parsed_args.command == "add":
        config = Config(offline=parsed_args.offline)
        add_params = AddParams(
            chunker=parsed_args.chunker,
            hash_fun=parsed_args.hash_fun,
            raw_leaves=parsed_args.raw_leaves,
        )
        trio.run(
            run_add,
            parsed_args.file,
            parsed_args.port,
            parsed_args.seed,
            config,
            add_params,
        )

    elif parsed_args.command == "get":
        config = Config(offline=parsed_args.offline)
        trio.run(
            run_get,
            parsed_args.cid,
            parsed_args.provider,
            parsed_args.out,
            parsed_args.port,
            parsed_args.seed,
            config,
        )


if __name__ == "__main__":
    main()

#!/usr/import/env python3
import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys

import trio
from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.utils.address_validation import find_free_port, get_available_interfaces
from libp2p.bitswap.cid import format_cid_for_display

from py_ipfs_lite.config import Config, AddParams
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.setup import setup_libp2p, new_in_memory_datastore

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

def load_config(config_path: str) -> dict:
    path = Path(config_path)
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {}

def format_size(size_bytes: int) -> str:
    """Format size in human-readable form."""
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

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
    host, routing = await setup_libp2p(
        host_key=key_pair,
        secret=None,
        listen_addrs=listen_addrs,
        datastore=None
    )

    async with host.run(listen_addrs=listen_addrs):
        peer = await Peer.new(
            datastore=new_in_memory_datastore(),
            blockstore=None,
            host=host,
            routing=routing,
            config=config,
        )

        logger.info(f"Daemon Peer ID: {host.get_id()}")
        addrs = host.get_addrs()
        logger.info(f"Listening on {len(addrs)} address(es):")
        for addr in addrs:
            logger.info(f"  {addr}")

        try:
            logger.info("Daemon is running. Press Ctrl+C to stop...")
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            await peer.close()

async def run_add(file_path: str, port: int, seed: str | None, config: Config, add_params: dict):
    """Add a file to the IPFS Lite network."""
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    key_pair = None
    if seed:
        seed_bytes = hashlib.sha256(seed.encode()).digest()
        key_pair = create_new_key_pair(seed=seed_bytes)

    host, routing = await setup_libp2p(
        host_key=key_pair,
        secret=None,
        listen_addrs=listen_addrs,
        datastore=None
    )

    async with host.run(listen_addrs=listen_addrs):
        peer = await Peer.new(
            datastore=new_in_memory_datastore(),
            blockstore=None,
            host=host,
            routing=routing,
            config=config,
        )
        
        logger.info(f"Adding file {file_path}...")
        try:
            params = AddParams(**add_params)
            
            with open(file_path_obj, "rb") as f:
                content = f.read()
            cid = await peer.add_file(content, params=params)
            logger.info(f"Added file successfully! CID: {format_cid_for_display(cid)}")
            
            logger.info("Provider is running. Press Ctrl+C to stop...")
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            await peer.close()

async def run_get(cid_str: str, provider_addr: str, out_file: str | None, port: int, seed: str | None, config: Config):
    """Fetch a file by CID."""
    from libp2p.peer.peerinfo import info_from_p2p_addr
    from libp2p.bitswap.cid import parse_cid

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    key_pair = None
    if seed:
        seed_bytes = hashlib.sha256(seed.encode()).digest()
        key_pair = create_new_key_pair(seed=seed_bytes)

    host, routing = await setup_libp2p(
        host_key=key_pair,
        secret=None,
        listen_addrs=listen_addrs,
        datastore=None
    )

    async with host.run(listen_addrs=listen_addrs):
        peer = await Peer.new(
            datastore=new_in_memory_datastore(),
            blockstore=None,
            host=host,
            routing=routing,
            config=config,
        )

        try:
            maddr = Multiaddr(provider_addr)
            info = info_from_p2p_addr(maddr)
            logger.info(f"Connecting to provider: {info.peer_id}...")
            await host.connect(info)
            logger.info("Connected!")

            cid = parse_cid(cid_str)
            logger.info(f"Fetching CID: {cid_str}...")
            
            content = await peer.get_file(cid)
            logger.info(f"Fetched {len(content)} bytes.")

            if out_file:
                with open(out_file, "wb") as f:
                    f.write(content)
                logger.info(f"Saved to {out_file}")
            else:
                logger.info("File content:")
                print(content.decode("utf-8", errors="replace"))

        finally:
            await peer.close()

def main():
    from py_ipfs_lite.parser import get_parser
    parser = get_parser()

    parsed_args = parser.parse_args()

    # Load config defaults
    config_defaults = load_config(parsed_args.config)

    # Resolve parameters (CLI overrides config file)
    def resolve_param(name, default_value=None):
        cli_val = getattr(parsed_args, name, None)
        if cli_val is not None and not (isinstance(cli_val, bool) and not cli_val):
            return cli_val
        return config_defaults.get(name, default_value)

    port = resolve_param("port", 0)
    seed = resolve_param("seed", None)
    
    if config_defaults.get("debug"):
        logging.getLogger().setLevel(logging.DEBUG)

    config_kwargs = {
        "offline": resolve_param("offline", False),
        "reprovide_interval_seconds": resolve_param("reprovide_interval_seconds", 43200),
    }
    config = Config(**config_kwargs)

    if parsed_args.command == "daemon":
        trio.run(run_daemon, port, seed, config)
    elif parsed_args.command == "add":
        add_params = {
            "chunker": resolve_param("chunker", "size-262144"),
            "hash_fun": resolve_param("hash_fun", "sha2-256"),
            "raw_leaves": resolve_param("raw_leaves", True),
        }
        trio.run(run_add, parsed_args.file, port, seed, config, add_params)
    elif parsed_args.command == "get":
        out_file = resolve_param("out", None)
        trio.run(run_get, parsed_args.cid, parsed_args.provider, out_file, port, seed, config)

if __name__ == "__main__":
    main()

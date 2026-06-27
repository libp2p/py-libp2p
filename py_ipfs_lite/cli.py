import hashlib
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import trio
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.utils.address_validation import find_free_port, get_available_interfaces

from py_ipfs_lite.config import AddParams, Config
from py_ipfs_lite.parser import get_parser
from py_ipfs_lite.peer import Peer

logger = logging.getLogger("py_ipfs_lite.cli")


def _get_key_pair(seed: str | None) -> Any:
    if seed:
        seed_bytes = hashlib.sha256(seed.encode()).digest()
        return create_new_key_pair(seed=seed_bytes)
    return None


DEFAULT_BOOTSTRAP_PEERS = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
]

from contextlib import asynccontextmanager


@asynccontextmanager
async def create_and_start_peer(
    port: int, seed: str | None, config: Config, bootstrap: bool = True
) -> AsyncGenerator[Any, None]:
    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    try:
        await peer.start()
        if bootstrap and not config.offline:
            logger.info("Connecting to IPFS bootstrap nodes...")
            await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
            logger.info("Successfully joined the DHT network!")
        yield peer
    finally:
        await peer.close()


async def run_daemon(port: int, seed: str | None, config: Config) -> None:
    """Run the IPFS Lite daemon (provider mode)."""
    logger.info("Starting py-ipfs-lite daemon...")
    try:
        async with create_and_start_peer(port, seed, config, bootstrap=True) as peer:
            logger.info(f"Daemon Peer ID: {peer.host.id()}")
            addrs = peer.host.addrs()
            logger.info(f"Listening on {len(addrs)} address(es):")
            for addr in addrs:
                logger.info(f"  {addr}")

            logger.info("Daemon is running. Press Ctrl+C to stop...")
            await trio.sleep_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")


async def run_add(
    file_path: str, port: int, seed: str | None, config: Config, add_params: AddParams
) -> None:
    """Add a file to the IPFS Lite network."""
    import os

    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return

    abs_path = os.path.abspath(file_path)

    logger.info(f"Adding file {file_path}...")
    try:
        async with create_and_start_peer(port, seed, config, bootstrap=True) as peer:
            cid = await peer.add_file(abs_path, params=add_params)
            logger.info(f"Added file successfully! CID: {cid}")
            logger.info(f"Provider Peer ID: {peer.host.id().to_base58()}")
            logger.info("Provide the following address to peers:")
            for addr in peer.host.addrs():
                logger.info(f"  {addr}")
    except Exception as e:
        logger.error(f"Error: {e}")


async def run_get(
    cid_str: str,
    provider_addr: str | None,
    out_file: str | None,
    port: int,
    seed: str | None,
    config: Config,
) -> None:
    """Fetch a file by CID."""
    import os

    out_path = os.path.abspath(out_file) if out_file else None

    logger.info(f"Fetching CID {cid_str}...")
    try:
        bootstrap = not bool(provider_addr)
        async with create_and_start_peer(
            port, seed, config, bootstrap=bootstrap
        ) as peer:
            content = await peer.get_file(
                cid_str, output_path=out_path, provider_addr=provider_addr
            )
            if out_path:
                import os

                logger.info(
                    f"Saved to {out_path} (size: {os.path.getsize(out_path)} bytes)"
                )
            else:
                logger.info(f"Fetched {len(content)} bytes")
                print(content.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.error(f"Error: {e}")


async def run_dag_export(
    cid_str: str, out_file: str, port: int, seed: str | None, config: Config
) -> None:
    """Export a DAG to a CAR file."""
    logger.info(f"Exporting DAG {cid_str} to CAR file {out_file}...")
    try:
        async with create_and_start_peer(port, seed, config, bootstrap=True) as peer:
            await peer.export_car(cid_str, out_file)
            logger.info(f"Successfully exported {cid_str} to {out_file}")
    except Exception as e:
        logger.error(f"Error exporting DAG: {e}")


async def run_dag_import(
    file_path: str, port: int, seed: str | None, config: Config
) -> None:
    """Import a CAR file into the blockstore."""
    import os

    if not os.path.exists(file_path):
        logger.error(f"CAR file not found: {file_path}")
        return

    logger.info(f"Importing CAR file {file_path}...")
    try:
        async with create_and_start_peer(port, seed, config, bootstrap=False) as peer:
            root_cids = await peer.import_car(file_path)
            logger.info("Successfully imported CAR file. Root CIDs:")
            for cid in root_cids:
                logger.info(f"  {cid}")
    except Exception as e:
        logger.error(f"Error importing CAR file: {e}")


def main() -> None:
    parser = get_parser()
    parsed_args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if parsed_args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    # Silence verbose loggers
    logging.getLogger("multiaddr.transforms").setLevel(logging.WARNING)
    logging.getLogger("multiaddr.codecs.cid").setLevel(logging.WARNING)
    logging.getLogger("libp2p.tools.anyio_service").setLevel(logging.WARNING)

    if parsed_args.command == "daemon":
        config = Config(
            offline=parsed_args.offline,
            reprovide_interval_seconds=parsed_args.reprovide_interval_seconds,
            blockstore_type=parsed_args.blockstore_type,
            blockstore_path=parsed_args.blockstore_path,
            use_ipni=parsed_args.use_ipni,
            ipni_endpoint=parsed_args.ipni_endpoint,
        )

        if parsed_args.api:
            import hypercorn.config
            import hypercorn.trio

            from py_ipfs_lite.api import app

            port = parsed_args.port
            if port <= 0:
                port = find_free_port()
            listen_addrs = get_available_interfaces(port)
            key_pair = _get_key_pair(parsed_args.seed)

            peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
            app.state.peer = peer

            hyperconfig = hypercorn.config.Config()
            hyperconfig.bind = [f"{parsed_args.api_host}:{parsed_args.api_port}"]

            logger.info(
                f"Starting py-ipfs-lite HTTP API daemon at http://{parsed_args.api_host}:{parsed_args.api_port}"
            )
            trio.run(hypercorn.trio.serve, app, hyperconfig)
        else:
            trio.run(run_daemon, parsed_args.port, parsed_args.seed, config)

    elif parsed_args.command == "add":
        config = Config(
            offline=parsed_args.offline,
            blockstore_type=parsed_args.blockstore_type,
            blockstore_path=parsed_args.blockstore_path,
            use_ipni=parsed_args.use_ipni,
            ipni_endpoint=parsed_args.ipni_endpoint,
        )
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
        config = Config(
            offline=parsed_args.offline,
            blockstore_type=parsed_args.blockstore_type,
            blockstore_path=parsed_args.blockstore_path,
            use_ipni=parsed_args.use_ipni,
            ipni_endpoint=parsed_args.ipni_endpoint,
        )
        trio.run(
            run_get,
            parsed_args.cid,
            parsed_args.provider,
            parsed_args.out,
            parsed_args.port,
            parsed_args.seed,
            config,
        )

    elif parsed_args.command == "dag-export":
        config = Config(
            offline=parsed_args.offline,
            blockstore_type=parsed_args.blockstore_type,
            blockstore_path=parsed_args.blockstore_path,
            use_ipni=parsed_args.use_ipni,
            ipni_endpoint=parsed_args.ipni_endpoint,
        )
        trio.run(
            run_dag_export,
            parsed_args.cid,
            parsed_args.out,
            parsed_args.port,
            parsed_args.seed,
            config,
        )

    elif parsed_args.command == "dag-import":
        config = Config(
            offline=parsed_args.offline,
            blockstore_type=parsed_args.blockstore_type,
            blockstore_path=parsed_args.blockstore_path,
            use_ipni=parsed_args.use_ipni,
            ipni_endpoint=parsed_args.ipni_endpoint,
        )
        trio.run(
            run_dag_import,
            parsed_args.file,
            parsed_args.port,
            parsed_args.seed,
            config,
        )


if __name__ == "__main__":
    main()

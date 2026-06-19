import hashlib
import logging
from pathlib import Path

import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.utils.address_validation import find_free_port, get_available_interfaces
from py_ipfs_lite.config import Config, AddParams
from py_ipfs_lite.parser import get_parser
from py_ipfs_lite.peer import Peer

logger = logging.getLogger("py_ipfs_lite.cli")

def _get_key_pair(seed: str | None):
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

async def run_daemon(port: int, seed: str | None, config: Config):
    """Run the IPFS Lite daemon (provider mode)."""
    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    logger.info("Starting py-ipfs-lite daemon...")
    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    
    try:
        await peer.start()
        logger.info(f"Daemon Peer ID: {peer.host.id()}")
        addrs = peer.host.addrs()
        logger.info(f"Listening on {len(addrs)} address(es):")
        for addr in addrs:
            logger.info(f"  {addr}")

        if not config.offline:
            logger.info("Connecting to IPFS bootstrap nodes...")
            await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
            logger.info("Successfully joined the DHT network!")

        logger.info("Daemon is running. Press Ctrl+C to stop...")
        await trio.sleep_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    finally:
        await peer.close()

async def run_add(
    file_path: str, port: int, seed: str | None, config: Config, add_params: AddParams
):
    """Add a file to the IPFS Lite network."""
    import os

    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return

    abs_path = os.path.abspath(file_path)

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    logger.info(f"Adding file {file_path}...")
    try:
        await peer.start()
        if not config.offline:
            logger.info("Connecting to IPFS bootstrap nodes...")
            await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
            
        cid = await peer.add_file(abs_path, params=add_params)
        logger.info(f"Added file successfully! CID: {cid}")
        logger.info(f"Provider Peer ID: {peer.host.id().to_base58()}")
        logger.info("Provide the following address to peers:")
        for addr in peer.host.addrs():
            logger.info(f"  {addr}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await peer.close()


async def run_get(
    cid_str: str,
    provider_addr: str | None,
    out_file: str | None,
    port: int,
    seed: str | None,
    config: Config,
):
    """Fetch a file by CID."""
    import os

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    out_path = os.path.abspath(out_file) if out_file else None

    logger.info(f"Fetching CID {cid_str}...")
    try:
        await peer.start()
        if not config.offline and not provider_addr:
            logger.info("Connecting to IPFS bootstrap nodes to search DHT...")
            await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
            
        content_or_iter = await peer.get_file(cid_str, output_path=out_path, provider_addr=provider_addr)
        if out_path:
            import os
            logger.info(f"Saved to {out_path} (size: {os.path.getsize(out_path)} bytes)")
        else:
            chunks = []
            async for chunk in content_or_iter:
                chunks.append(chunk)
            full_content = b"".join(chunks)
            logger.info(f"Fetched {len(full_content)} bytes")
            print(full_content.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await peer.close()

async def run_dag_export(cid_str: str, out_file: str, port: int, seed: str | None, config: Config):
    """Export a DAG to a CAR file."""
    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    
    logger.info(f"Exporting DAG {cid_str} to CAR file {out_file}...")
    try:
        await peer.start()
        if not config.offline:
            logger.info("Connecting to IPFS bootstrap nodes...")
            await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
            
        await peer.export_car(cid_str, out_file)
        logger.info("Export complete.")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await peer.close()

async def run_dag_import(file_path: str, port: int, seed: str | None, config: Config):
    """Import a CAR file into the blockstore."""
    import os
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    
    logger.info(f"Importing CAR file {file_path}...")
    try:
        await peer.start()
            
        roots = await peer.import_car(file_path)
        logger.info(f"Import complete. Imported roots: {roots}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await peer.close()

def main():
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
        )
        
        if parsed_args.api:
            import hypercorn.trio
            import hypercorn.config
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
            
            logger.info(f"Starting py-ipfs-lite HTTP API daemon at http://{parsed_args.api_host}:{parsed_args.api_port}")
            trio.run(hypercorn.trio.serve, app, hyperconfig)
        else:
            trio.run(run_daemon, parsed_args.port, parsed_args.seed, config)

    elif parsed_args.command == "add":
        config = Config(
            offline=parsed_args.offline,
            blockstore_type=parsed_args.blockstore_type,
            blockstore_path=parsed_args.blockstore_path,
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

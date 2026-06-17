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

        logger.info("Daemon is running. Press Ctrl+C to stop...")
        await trio.sleep_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    finally:
        await peer.close()

async def run_add(
    file_path: str, port: int, seed: str | None, config: Config, add_params: AddParams, api_host: str = "127.0.0.1", api_port: int = 5001
):
    """Add a file to the IPFS Lite network."""
    import os
    import json
    import urllib.request
    import urllib.error

    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return

    abs_path = os.path.abspath(file_path)
    
    # Try HTTP API first
    api_url = f"http://{api_host}:{api_port}/api/v0/add"
    try:
        with open(abs_path, "rb") as f:
            file_data = f.read()
            
        boundary = "----pyIpfsLiteBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(abs_path)}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            api_url, 
            data=body, 
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                res_data = json.loads(response.read().decode())
                logger.info(f"Added file successfully via HTTP API! CID: {res_data.get('Hash')}")
                return
    except urllib.error.URLError:
        # Daemon not running or unreachable, fallback to ephemeral node
        pass

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)
    logger.info(f"Adding file {file_path} via ephemeral P2P node...")
    try:
        await peer.start()
        cid = await peer.add_file(abs_path)
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
    api_host: str = "127.0.0.1",
    api_port: int = 5001,
):
    """Fetch a file by CID."""
    import os
    import urllib.request
    import urllib.error

    out_path = os.path.abspath(out_file) if out_file else None

    # Try HTTP API first
    api_url = f"http://{api_host}:{api_port}/api/v0/cat?arg={cid_str}"
    try:
        req = urllib.request.Request(api_url, method="POST")
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                content = response.read()
                if out_path:
                    with open(out_path, "wb") as f:
                        f.write(content)
                    logger.info(f"Saved {len(content)} bytes to {out_path} via HTTP API")
                else:
                    logger.info(f"Fetched {len(content)} bytes via HTTP API")
                    print(content.decode("utf-8", errors="replace"))
                return
    except urllib.error.URLError:
        # Daemon not running or unreachable, fallback to ephemeral node
        pass

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)
    key_pair = _get_key_pair(seed)

    peer = Peer(config, host_key=key_pair, listen_addrs=listen_addrs)

    logger.info(f"Fetching CID {cid_str} via ephemeral P2P node...")
    try:
        await peer.start()
        content = await peer.get_file(cid_str, output_path=out_path, provider_addr=provider_addr)
        if out_path:
            logger.info(f"Saved {len(content)} bytes to {out_path}")
        else:
            logger.info(f"Fetched {len(content)} bytes")
            print(content.decode("utf-8", errors="replace"))
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
            parsed_args.api_host,
            parsed_args.api_port,
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
            parsed_args.api_host,
            parsed_args.api_port,
        )

if __name__ == "__main__":
    main()

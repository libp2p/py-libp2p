#!/usr/bin/env python3

import argparse
import hashlib
import logging
from pathlib import Path
import sys

import trio

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.bitswap import BitswapClient
from libp2p.bitswap.cid import cid_to_bytes, format_cid_for_display
from libp2p.bitswap.dag import MerkleDag
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)

# Silence verbose loggers
logging.getLogger("multiaddr.transforms").setLevel(logging.WARNING)
logging.getLogger("multiaddr.codecs.cid").setLevel(logging.WARNING)
logging.getLogger("libp2p.tools.anyio_service").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

DEFAULT_LISTEN_PORT = 4013


def select_preferred_listen_addr(addrs: list[Multiaddr], port: int) -> Multiaddr:
    """Pick a stable, local-friendly address for copy/paste commands."""
    preferred_v4 = f"/ip4/127.0.0.1/tcp/{port}"
    for addr in addrs:
        if str(addr) == preferred_v4:
            return addr

    preferred_v6 = f"/ip6/::1/tcp/{port}"
    for addr in addrs:
        if str(addr) == preferred_v6:
            return addr

    return addrs[0]


def format_size(size_bytes: int) -> str:
    """Format size in human-readable form."""
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def run_provider(file_path: str, port: int = 0, seed: str | None = None):
    """
    Run the provider node to share a file.

    Args:
        file_path: Path to the file to share
        port: TCP port to listen on (0 for auto)
        seed: Optional seed string for deterministic peer ID generation

    """
    file_path_obj = Path(file_path)

    if not file_path_obj.exists():
        logger.error(f"File not found: {file_path}")
        return

    file_size = file_path_obj.stat().st_size
    logger.info("=" * 70)
    logger.info("PROVIDER NODE STARTING")
    logger.info("=" * 70)
    logger.info(f"File: {file_path}")
    logger.info(f"Size: {format_size(file_size)}")
    logger.info(f"Port: {port if port > 0 else 'auto'}")
    logger.info("=" * 70)

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    # Create host with optional seed for deterministic peer ID
    key_pair = None
    if seed:
        # Convert seed string to bytes (must be 32 bytes for Ed25519)
        seed_bytes = hashlib.sha256(seed.encode()).digest()
        key_pair = create_new_key_pair(seed=seed_bytes)
        logger.info("Using deterministic peer ID from seed")

    host = new_host(key_pair=key_pair)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        logger.info(f"Peer ID: {host.get_id()}")

        # Get actual listening addresses
        addrs = host.get_addrs()
        logger.info(f"Listening on {len(addrs)} address(es):")
        for addr in addrs:
            logger.info(f"  {addr}")

        # Start Bitswap
        bitswap = BitswapClient(host)
        await bitswap.start()
        logger.info("✓ Bitswap started")

        # Set nursery so bitswap can spawn background tasks
        bitswap.set_nursery(nursery)
        dag = MerkleDag(bitswap)

        logger.info("")
        logger.info("Adding file to DAG...")

        # Track progress
        def progress_callback(current: int, total: int, status: str):
            if total > 0:
                percent = current / total * 100
                logger.info(
                    f"  📤 {status}: {percent:.1f}% "
                    f"({format_size(current)}/{format_size(total)})"
                )

        # Add file with directory wrapper for filename preservation
        # Always uses Merkle DAG regardless of file size
        root_cid = await dag.add_file(
            file_path, progress_callback=progress_callback, wrap_with_directory=False
        )

        # Get all blocks that were stored
        logger.info("")
        logger.info("=" * 70)
        logger.info("BLOCKS CREATED:")
        logger.info("=" * 70)
        all_cids = bitswap.block_store.get_all_cids()
        logger.info(f"Total blocks stored: {len(all_cids)}")
        for i, cid in enumerate(all_cids, 1):
            block_data = await bitswap.block_store.get_block(cid)
            block_size = len(block_data) if block_data else 0
            logger.info(
                f"  {i}. {format_cid_for_display(cid)} ({format_size(block_size)})"
            )

        logger.info("")
        logger.info("=" * 70)
        logger.info("FILE READY TO SHARE!")
        logger.info("=" * 70)

        # Prefer a deterministic local address for copy/paste commands.
        transport_addrs = host.get_transport_addrs()
        provider_addr = select_preferred_listen_addr(transport_addrs, port)
        provider_addr = provider_addr.encapsulate(Multiaddr(f"/p2p/{host.get_id()}"))
        root_cid_text = format_cid_for_display(root_cid)
        logger.info(f"Root CID:  {root_cid_text}")
        logger.info("")
        logger.info("=" * 70)
        logger.info("📋 COPY THIS COMMAND TO RUN CLIENT:")
        logger.info("=" * 70)
        logger.info(
            f"python bitswap.py --mode client "
            f'--provider "{provider_addr}" --cid "{root_cid_text}"'
        )
        logger.info("=" * 70)
        logger.info("")
        logger.info("Provider is running. Press Ctrl+C to stop...")

        # Keep running
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            await bitswap.stop()


async def run_client(
    provider_multiaddr_str: str,
    root_cid_input: str,
    output_dir: str = "/tmp",
    port: int = 0,
    seed: str | None = None,
):
    """
    Run the client node to fetch a file.

    Args:
        provider_multiaddr_str: Provider's multiaddress
        root_cid_input: Root CID (canonical text, /ipfs/... path, or hex string)
        output_dir: Directory to save the file
        port: TCP port to listen on (0 for auto)
        seed: Optional seed string for deterministic peer ID generation

    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        provider_multiaddr = Multiaddr(provider_multiaddr_str)
        root_cid = cid_to_bytes(root_cid_input)
        root_cid_text = format_cid_for_display(root_cid)
    except Exception as e:
        logger.error(f"Invalid input: {e}")
        return

    logger.info("=" * 70)
    logger.info("CLIENT NODE STARTING")
    logger.info("=" * 70)
    logger.info(f"Provider:   {provider_multiaddr}")
    logger.info(f"Root CID:   {root_cid_text}")
    logger.info(f"Output dir: {output_path}")
    logger.info("=" * 70)

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    # Create host with optional seed for deterministic peer ID
    key_pair = None
    if seed:
        # Convert seed string to bytes (must be 32 bytes for Ed25519)
        seed_bytes = hashlib.sha256(seed.encode()).digest()
        key_pair = create_new_key_pair(seed=seed_bytes)
        logger.info("Using deterministic peer ID from seed")

    host = new_host(key_pair=key_pair)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        logger.info(f"Client Peer ID: {host.get_id()}")

        # Start Bitswap
        bitswap = BitswapClient(host)
        await bitswap.start()
        logger.info("✓ Bitswap started")
        bitswap.set_nursery(nursery)

        try:
            # Connect to provider
            logger.info("")
            logger.info("Connecting to provider...")
            peer_info = info_from_p2p_addr(provider_multiaddr)
            await host.connect(peer_info)
            logger.info("✓ Connected")

            dag = MerkleDag(bitswap)

            logger.info("")
            logger.info("Fetching file...")

            # Progress callback
            def progress_callback(current: int, total: int, status: str):
                if total > 0:
                    percent = current / total * 100
                    logger.info(
                        f"  📥 {status}: {percent:.1f}% "
                        f"({format_size(current)}/{format_size(total)})"
                    )

            # Fetch file with automatic filename extraction
            try:
                file_data, filename = await dag.fetch_file(
                    root_cid, progress_callback=progress_callback, timeout=120.0
                )

                # Show fetch statistics
                logger.info("")
                logger.info("=" * 70)
                logger.info("FETCH STATISTICS:")
                logger.info("=" * 70)
                all_blocks = bitswap.block_store.get_all_cids()
                logger.info(f"Total blocks fetched: {len(all_blocks)}")
                for i, cid in enumerate(all_blocks, 1):
                    block_data = await bitswap.block_store.get_block(cid)
                    block_size = len(block_data) if block_data else 0
                    logger.info(
                        f"  ✓ {i}. {format_cid_for_display(cid)} "
                        f"({format_size(block_size)})"
                    )

            except Exception as fetch_error:
                # Show what failed
                logger.error("")
                logger.error("=" * 70)
                logger.error("FETCH FAILED!")
                logger.error("=" * 70)
                logger.error(f"Error: {fetch_error}")

                # Show blocks we did get
                all_blocks = bitswap.block_store.get_all_cids()
                if all_blocks:
                    logger.error(f"Blocks successfully fetched: {len(all_blocks)}")
                    for i, cid in enumerate(all_blocks, 1):
                        block_data = await bitswap.block_store.get_block(cid)
                        block_size = len(block_data) if block_data else 0
                        logger.error(
                            f"  ✓ {i}. {format_cid_for_display(cid)} "
                            f"({format_size(block_size)})"
                        )
                else:
                    logger.error("No blocks were successfully fetched")

                # Show what we were trying to get
                logger.error("")
                logger.error("Missing/Failed blocks can be seen in the logs above")
                logger.error("=" * 70)
                raise

            logger.info("")
            logger.info("=" * 70)
            logger.info("FILE DOWNLOADED!")
            logger.info("=" * 70)
            logger.info(f"Size: {format_size(len(file_data))}")

            # Determine output filename (priority: metadata > generated)
            if filename:
                final_filename = filename
                logger.info(f"Filename: {final_filename} (from metadata)")
            else:
                final_filename = (
                    f"file_{format_cid_for_display(root_cid, max_len=16)}.bin"
                )
                logger.info(f"Filename: {final_filename} (generated from CID)")

            # Handle filename conflicts
            output_file = output_path / final_filename
            if output_file.exists():
                stem = output_file.stem
                suffix = output_file.suffix
                counter = 1
                while output_file.exists():
                    output_file = output_path / f"{stem}_{counter}{suffix}"
                    counter += 1
                logger.info(f"⚠ File exists, saving as: {output_file.name}")

            # Save file
            with open(output_file, "wb") as f:
                f.write(file_data)

            logger.info(f"✓ Saved to: {output_file}")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"Failed: {e}")
            logger.exception("Full traceback:")
            raise
        finally:
            pass  # Nursery will cleanup background tasks
            await bitswap.stop()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Bitswap file sharing example - provider and client modes"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["provider", "client"],
        help="Run as provider or client",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_LISTEN_PORT,
        help=("Port to listen on (default: 4012). Use 0 to auto-select a random port."),
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Path to file to share (provider mode only)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        help="Provider's multiaddress (client mode only)",
    )
    parser.add_argument(
        "--cid",
        type=str,
        help=(
            "Root CID (canonical text, /ipfs/... path, or legacy hex string; "
            "client mode only)"
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default="/tmp",
        help="Output directory for downloaded files (client mode only, default: /tmp)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--seed",
        type=str,
        help=(
            "Seed string for deterministic peer ID generation "
            "(same seed = same peer ID)"
        ),
    )

    args = parser.parse_args()

    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Validate mode-specific arguments
    if args.mode == "provider":
        if not args.file:
            parser.error("--file is required in provider mode")
    elif args.mode == "client":
        if not args.provider or not args.cid:
            parser.error("--provider and --cid are required in client mode")

    return args


def main():
    """Main entry point for the bitswap demo."""
    try:
        args = parse_args()
        logger.info(
            "Running in %s mode",
            args.mode,
        )

        if args.mode == "provider":
            trio.run(run_provider, args.file, args.port, args.seed)
        elif args.mode == "client":
            trio.run(
                run_client, args.provider, args.cid, args.output, args.port, args.seed
            )
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

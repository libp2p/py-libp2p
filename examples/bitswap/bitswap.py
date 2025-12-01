#!/usr/bin/env python3

import argparse
import logging
from pathlib import Path
import sys

import trio

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.bitswap import BitswapClient
from libp2p.bitswap.dag import MerkleDag
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
logging.getLogger("async_service.Manager").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """Format size in human-readable form."""
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def run_provider(file_path: str, port: int = 0):
    """
    Run the provider node to share a file.

    Args:
        file_path: Path to the file to share
        port: TCP port to listen on (0 for auto)

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
    # Create host
    host = new_host()

    async with host.run(listen_addrs=listen_addrs):
        peer_id = host.get_id()
        logger.info(f"Peer ID: {peer_id}")

        # Get actual listening addresses
        addrs = host.get_addrs()
        logger.info(f"Listening on {len(addrs)} address(es):")
        for addr in addrs:
            logger.info(f"  {addr}")

        # Start Bitswap
        bitswap = BitswapClient(host)
        await bitswap.start()
        logger.info("✓ Bitswap started")

        # Create Merkle DAG
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
            file_path, progress_callback=progress_callback, wrap_with_directory=True
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
            logger.info(f"  {i}. {cid.hex()} ({format_size(block_size)})")

        logger.info("")
        logger.info("=" * 70)
        logger.info("FILE READY TO SHARE!")
        logger.info("=" * 70)

        # Get the first address (clean multiaddr without duplicate /p2p/)
        provider_addr = host.get_addrs()[0]
        logger.info(f"Root CID:  {root_cid.hex()}")
        logger.info("")
        logger.info("=" * 70)
        logger.info("📋 COPY THIS COMMAND TO RUN CLIENT:")
        logger.info("=" * 70)
        logger.info(
            f"python bitswap.py --mode client "
            f'--provider "{provider_addr}" --cid "{root_cid.hex()}"'
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
    root_cid_hex: str,
    output_dir: str = "/tmp",
    port: int = 0,
):
    """
    Run the client node to fetch a file.

    Args:
        provider_multiaddr_str: Provider's multiaddress
        root_cid_hex: Root CID as hex string
        output_dir: Directory to save the file
        port: TCP port to listen on (0 for auto)

    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        provider_multiaddr = Multiaddr(provider_multiaddr_str)
        root_cid = bytes.fromhex(root_cid_hex)
    except Exception as e:
        logger.error(f"Invalid input: {e}")
        return

    logger.info("=" * 70)
    logger.info("CLIENT NODE STARTING")
    logger.info("=" * 70)
    logger.info(f"Provider:   {provider_multiaddr}")
    logger.info(f"Root CID:   {root_cid_hex}")
    logger.info(f"Output dir: {output_path}")
    logger.info("=" * 70)

    if port <= 0:
        port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    # Create host
    host = new_host()

    async with host.run(listen_addrs=listen_addrs):
        logger.info(f"Client Peer ID: {host.get_id()}")

        # Start Bitswap
        bitswap = BitswapClient(host)
        await bitswap.start()
        logger.info("✓ Bitswap started")

        try:
            # Connect to provider
            logger.info("")
            logger.info("Connecting to provider...")
            peer_info = info_from_p2p_addr(provider_multiaddr)
            await host.connect(peer_info)
            logger.info("✓ Connected")

            # Create Merkle DAG
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
                    root_cid, progress_callback=progress_callback
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
                    logger.info(f"  ✓ {i}. {cid.hex()} ({format_size(block_size)})")

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
                            f"  ✓ {i}. {cid.hex()} ({format_size(block_size)})"
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

            # Determine output filename
            if filename:
                output_filename = filename
                logger.info(f"Filename: {filename} (from metadata)")
            else:
                output_filename = f"file_{root_cid_hex[:16]}.bin"
                logger.info(f"Filename: {output_filename} (no metadata)")

            # Handle filename conflicts
            output_file = output_path / output_filename
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
        finally:
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
        default=0,
        help="Port to listen on (0 for random, provider mode only)",
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
        help="Root CID as hex string (client mode only)",
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
            trio.run(run_provider, args.file, args.port)
        elif args.mode == "client":
            trio.run(run_client, args.provider, args.cid, args.output, args.port)
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

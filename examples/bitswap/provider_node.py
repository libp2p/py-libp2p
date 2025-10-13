#!/usr/bin/env python3
"""
Provider Node - Shares a file via Bitswap

Usage: python provider_node.py <file_path> [port]
Example: python provider_node.py /path/to/file.pdf 8000
"""

import argparse
import logging
import sys
from pathlib import Path

import trio

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libp2p import new_host
from libp2p.bitswap import BitswapClient
from libp2p.bitswap.dag import MerkleDag
from multiaddr import Multiaddr
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
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
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


async def run_provider(file_path: str, port: int = 0):
    """Run the provider node."""
    file_path_obj = Path(file_path)
    port = find_free_port()
    listen_addr = get_available_interfaces(port)
    
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
    
    # Create host
    host = new_host()
    
    async with host.run(listen_addrs=listen_addr):
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
        
        # Track chunks/blocks created
        chunks_created = []
        
        # Track progress
        def progress_callback(current: int, total: int, status: str):
            if total > 0:
                percent = (current / total * 100)
                logger.info(f"  📤 {status}: {percent:.1f}% ({format_size(current)}/{format_size(total)})")
        
        # Add file with directory wrapper for filename preservation
        root_cid = await dag.add_file(
            file_path,
            progress_callback=progress_callback,
            wrap_with_directory=True
        )
        
        # Get all blocks that were stored
        logger.info("")
        logger.info("=" * 70)
        logger.info("BLOCKS CREATED:")
        logger.info("=" * 70)
        all_cids = list(bitswap.block_store._blocks.keys())
        logger.info(f"Total blocks stored: {len(all_cids)}")
        for i, cid in enumerate(all_cids, 1):
            block_size = len(bitswap.block_store._blocks[cid])
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
        logger.info(f"python client_node.py \"{provider_addr}\" \"{root_cid.hex()}\"")
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Share files over Bitswap")
    parser.add_argument("file_path", help="Path to file to share")
    parser.add_argument("port", type=int, nargs="?", default=0, help="TCP port (default: random)")
    
    args = parser.parse_args()
    
    try:
        trio.run(run_provider, args.file_path, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

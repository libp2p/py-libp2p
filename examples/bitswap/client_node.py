#!/usr/bin/env python3
"""
Client Node - Fetches a file via Bitswap

Usage: python client_node.py <provider_multiaddr> <root_cid> [output_dir]
Example: python client_node.py "/ip4/127.0.0.1/tcp/8000/p2p/QmYyQSo..." "bafybeig..." /tmp
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
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr

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


async def run_client(provider_multiaddr_str: str, root_cid_hex: str, output_dir: str = "/tmp"):
    """Run the client node."""
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
    
    # Create host
    host = new_host()
    
    async with host.run(listen_addrs=[Multiaddr("/ip4/0.0.0.0/tcp/0")]):
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
            
            # Track fetch progress
            fetch_stats = {
                'blocks_fetched': [],
                'blocks_failed': [],
                'total_bytes': 0
            }
            
            # Progress callback
            def progress_callback(current: int, total: int, status: str):
                if total > 0:
                    percent = (current / total * 100)
                    logger.info(f"  📥 {status}: {percent:.1f}% ({format_size(current)}/{format_size(total)})")
            
            # Fetch file with automatic filename extraction
            try:
                file_data, filename = await dag.fetch_file(root_cid, progress_callback=progress_callback)
                
                # Show fetch statistics
                logger.info("")
                logger.info("=" * 70)
                logger.info("FETCH STATISTICS:")
                logger.info("=" * 70)
                all_blocks = list(bitswap.block_store._blocks.keys())
                logger.info(f"Total blocks fetched: {len(all_blocks)}")
                for i, cid in enumerate(all_blocks, 1):
                    block_size = len(bitswap.block_store._blocks[cid])
                    logger.info(f"  ✓ {i}. {cid.hex()} ({format_size(block_size)})")
                
            except Exception as fetch_error:
                # Show what failed
                logger.error("")
                logger.error("=" * 70)
                logger.error("FETCH FAILED!")
                logger.error("=" * 70)
                logger.error(f"Error: {fetch_error}")
                
                # Show blocks we did get
                all_blocks = list(bitswap.block_store._blocks.keys())
                if all_blocks:
                    logger.error(f"Blocks successfully fetched: {len(all_blocks)}")
                    for i, cid in enumerate(all_blocks, 1):
                        block_size = len(bitswap.block_store._blocks[cid])
                        logger.error(f"  ✓ {i}. {cid.hex()} ({format_size(block_size)})")
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Fetch files over Bitswap")
    parser.add_argument("provider_multiaddr", help="Provider's multiaddress")
    parser.add_argument("root_cid", help="Root CID (hex string)")
    parser.add_argument("output_dir", nargs="?", default="/tmp", help="Output directory (default: /tmp)")
    
    args = parser.parse_args()
    
    try:
        trio.run(run_client, args.provider_multiaddr, args.root_cid, args.output_dir)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

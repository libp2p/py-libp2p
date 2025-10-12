#!/usr/bin/env python3
"""
Provider Node - Shares a file via Bitswap

This script:
1. Reads configuration from provider_config.json
2. Creates a libp2p host and starts Bitswap
3. Adds the file to Merkle DAG
4. Saves connection info to shared_config.json for the client
5. Keeps running to serve blocks to clients
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import trio

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libp2p import new_host
from libp2p.bitswap import BitswapClient
from libp2p.bitswap.dag import MerkleDag
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


async def run_provider():
    """Run the provider node."""
    
    # Load provider configuration from Desktop
    desktop_path = Path.home() / "Desktop"
    config_file = desktop_path / "provider_config.json"
    if not config_file.exists():
        logger.error(f"Configuration file not found: {config_file}")
        logger.error("Please create provider_config.json with your settings")
        logger.error('Example: {"file_path": "/path/to/your/file.txt", "port": 0}')
        return
    
    with open(config_file, "r") as f:
        config = json.load(f)
    
    file_path = Path(config["file_path"])
    port = config.get("port", 0)  # 0 = random port
    
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return
    
    file_size = file_path.stat().st_size
    logger.info("=" * 60)
    logger.info("PROVIDER NODE STARTING")
    logger.info("=" * 60)
    logger.info(f"File: {file_path}")
    logger.info(f"Size: {format_size(file_size)}")
    logger.info(f"Port: {port if port > 0 else 'random'}")
    logger.info("=" * 60)
    
    # Create host
    host = new_host()
    
    async with host.run(listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]):
        logger.info(f"Host created with Peer ID: {host.get_id()}")
        
        # Get actual listening addresses
        addrs = host.get_addrs()
        logger.info(f"Listening on {len(addrs)} address(es):")
        for addr in addrs:
            logger.info(f"  {addr}")
        
        # Start Bitswap
        bitswap = BitswapClient(host)
        await bitswap.start()
        logger.info("Bitswap started")
        
        # Create Merkle DAG
        dag = MerkleDag(bitswap)
        
        # Add file to DAG
        logger.info("")
        logger.info("=" * 60)
        logger.info("ADDING FILE TO MERKLE DAG")
        logger.info("=" * 60)
        logger.info("This may take a moment for large files...")
        logger.info("")
        
        # Track progress
        def progress_callback(current: int, total: int, status: str):
            logger.info(f"{status}: {current}/{total} bytes")
        
        root_cid = await dag.add_file(str(file_path), progress_callback=progress_callback)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("FILE SUCCESSFULLY ADDED!")
        logger.info("=" * 60)
        logger.info(f"Root CID: {root_cid.hex()}")
        logger.info("=" * 60)
        
        # Save connection info for client
        # Use the first address (usually the best one)
        provider_addr = str(addrs[0]) if addrs else None
        
        if not provider_addr:
            logger.error("No listening addresses available!")
            return
        
        shared_config = {
            "provider_multiaddr": provider_addr,
            "root_cid": root_cid.hex(),
            "file_name": file_path.name,
            "file_size": file_size,
        }
        
        shared_config_file = desktop_path / "shared_config.json"
        with open(shared_config_file, "w") as f:
            json.dump(shared_config, f, indent=2)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("CONNECTION INFO SAVED")
        logger.info("=" * 60)
        logger.info(f"Config file: {shared_config_file}")
        logger.info(f"Provider address: {provider_addr}")
        logger.info(f"Root CID: {root_cid.hex()}")
        logger.info("=" * 60)
        logger.info("")
        logger.info("✓ Provider is ready! You can now run client_node.py")
        logger.info("")
        logger.info("Press Ctrl+C to stop the provider...")
        
        # Keep running to serve blocks
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("\nShutting down provider...")
        finally:
            await bitswap.stop()
            logger.info("Provider stopped")


def main():
    """Main entry point."""
    trio.run(run_provider)


if __name__ == "__main__":
    main()

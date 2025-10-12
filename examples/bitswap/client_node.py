#!/usr/bin/env python3
"""
Client Node - Fetches a file via Bitswap

This script:
1. Reads configuration from client_config.json (for output path)
2. Reads connection info from shared_config.json (created by provider)
3. Creates a libp2p host and starts Bitswap
4. Connects to the provider
5. Fetches the file using the root CID
6. Verifies and saves the file
"""

import asyncio
import json
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


async def run_client():
    """Run the client node."""
    
    # Load client configuration from Desktop
    desktop_path = Path.home() / "Desktop"
    client_config_file = desktop_path / "client_config.json"
    if not client_config_file.exists():
        logger.error(f"Configuration file not found: {client_config_file}")
        logger.error("Please create client_config.json with your settings")
        logger.error('Example: {"output_dir": "/tmp"}')
        return
    
    with open(client_config_file, "r") as f:
        client_config = json.load(f)
    
    output_dir = Path(client_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load shared configuration (from provider) from Desktop
    shared_config_file = desktop_path / "shared_config.json"
    if not shared_config_file.exists():
        logger.error(f"Shared configuration file not found: {shared_config_file}")
        logger.error("Please run provider_node.py first!")
        return
    
    with open(shared_config_file, "r") as f:
        shared_config = json.load(f)
    
    provider_multiaddr = Multiaddr(shared_config["provider_multiaddr"])
    root_cid = bytes.fromhex(shared_config["root_cid"])
    file_name = shared_config["file_name"]
    expected_size = shared_config["file_size"]
    
    output_file = output_dir / f"received_{file_name}"
    
    logger.info("=" * 60)
    logger.info("CLIENT NODE STARTING")
    logger.info("=" * 60)
    logger.info(f"Provider: {provider_multiaddr}")
    logger.info(f"Root CID: {shared_config['root_cid']}")
    logger.info(f"Expected size: {format_size(expected_size)}")
    logger.info(f"Output file: {output_file}")
    logger.info("=" * 60)
    
    # Create host
    host = new_host()
    
    async with host.run(listen_addrs=[Multiaddr("/ip4/0.0.0.0/tcp/0")]):
        logger.info(f"Host created with Peer ID: {host.get_id()}")
        
        # Get listening addresses
        addrs = host.get_addrs()
        logger.info(f"Listening on {len(addrs)} address(es)")
        
        # Start Bitswap
        bitswap = BitswapClient(host)
        await bitswap.start()
        logger.info("Bitswap started")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("CONNECTING TO PROVIDER")
        logger.info("=" * 60)
        
        try:
            peer_info = info_from_p2p_addr(provider_multiaddr)
            await host.connect(peer_info)
            logger.info(f"✓ Connected to provider: {provider_multiaddr}")
        except Exception as e:
            logger.error(f"Failed to connect to provider: {e}")
            await bitswap.stop()
            return
        
        # Create Merkle DAG
        dag = MerkleDag(bitswap)
        
        # Fetch file
        logger.info("")
        logger.info("=" * 60)
        logger.info("FETCHING FILE")
        logger.info("=" * 60)
        logger.info("This may take a moment for large files...")
        logger.info("")
        
        # Track progress
        def progress_callback(current: int, total: int, status: str):
            percent = (current / total * 100) if total > 0 else 0
            logger.info(f"📥 {status}: {percent:.1f}% ({current}/{total} bytes)")
        
        try:
            file_data = await dag.fetch_file(root_cid, progress_callback=progress_callback)
            
            logger.info("")
            logger.info("=" * 60)
            logger.info("FILE SUCCESSFULLY FETCHED!")
            logger.info("=" * 60)
            logger.info(f"Downloaded: {format_size(len(file_data))}")
            logger.info(f"Expected: {format_size(expected_size)}")
            
            # Verify size
            if len(file_data) == expected_size:
                logger.info("✓ Size verification: PASSED")
            else:
                logger.warning(f"⚠ Size mismatch! Got {len(file_data)}, expected {expected_size}")
            
            # Save file
            with open(output_file, "wb") as f:
                f.write(file_data)
            
            logger.info(f"✓ File saved to: {output_file}")
            logger.info("=" * 60)
            
            # Show first few bytes
            preview = file_data[:100]
            if len(file_data) > 100:
                preview_text = preview.decode("utf-8", errors="replace") + "..."
            else:
                preview_text = preview.decode("utf-8", errors="replace")
            
            logger.info("")
            logger.info("File preview (first 100 bytes):")
            logger.info(preview_text)
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Failed to fetch file: {e}")
            logger.exception("Full traceback:")
        finally:
            await bitswap.stop()
            logger.info("Client stopped")


def main():
    """Main entry point."""
    trio.run(run_client)


if __name__ == "__main__":
    main()

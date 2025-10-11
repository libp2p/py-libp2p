#!/usr/bin/env python3
"""
Simple example demonstrating Bitswap protocol usage for file sharing.

This example shows how to:
1. Start a Bitswap node with blocks
2. Start another node that requests blocks
3. Exchange blocks between peers using Bitswap
"""

import argparse
import hashlib
import logging
from pathlib import Path
import sys

# Add parent directory to path to import libp2p
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import multiaddr
import trio

from libp2p import new_host
from libp2p.bitswap import BitswapClient, MemoryBlockStore, compute_cid
from libp2p.peer.peerinfo import info_from_p2p_addr

# Enable logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("libp2p.bitswap").setLevel(logging.DEBUG)

# Create logger for this example
logger = logging.getLogger("bitswap_example")


async def run_provider(port: int = 0, file_path: str | None = None) -> None:
    """
    Run a Bitswap provider node that serves blocks.

    Args:
        port: Port to listen on (0 for random)
        file_path: Optional path to a file to share

    """
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host()

    async with host.run([listen_addr]), trio.open_nursery() as nursery:
        # Create Bitswap client with block store
        block_store = MemoryBlockStore()
        bitswap = BitswapClient(host, block_store)
        bitswap.set_nursery(nursery)
        await bitswap.start()

        # Add some example blocks
        if file_path and Path(file_path).exists():
            # Read file and split into blocks
            with open(file_path, "rb") as f:
                file_data = f.read()

            # Split into blocks (1KB chunks)
            block_size = 1024
            blocks = []
            for i in range(0, len(file_data), block_size):
                chunk = file_data[i : i + block_size]
                cid = compute_cid(chunk)
                await bitswap.add_block(cid, chunk)
                blocks.append(cid)

            logger.info(f"Added {len(blocks)} blocks from file '{file_path}'")
            logger.info("Block CIDs:")
            for i, cid in enumerate(blocks):
                logger.info(f"  Block {i}: {cid.hex()}")

            # Show example command to fetch these blocks
            if blocks:
                logger.info("\nTo fetch these blocks from a client, use:")
                cids_arg = " ".join([cid.hex() for cid in blocks[:3]])
                logger.info(
                    f"  python bitswap.py --mode client --provider "
                    f"{host.get_addrs()[0]} --cids {cids_arg}"
                )
        else:
            # Add some example text blocks
            example_blocks = [
                b"Hello from Bitswap!",
                b"This is block number 2",
                b"Bitswap makes file sharing easy",
                b"Block exchange in py-libp2p",
            ]

            block_cids = []
            for i, data in enumerate(example_blocks):
                cid = compute_cid(data)
                await bitswap.add_block(cid, data)
                block_cids.append(cid)
                logger.info(f"Added block {i}: {cid.hex()} = {data.decode()}")

            # Show example command to fetch these blocks
            logger.info("\nTo fetch these blocks from a client, use:")
            cids_arg = " ".join([cid.hex() for cid in block_cids[:3]])
            logger.info(
                f"  python bitswap.py --mode client --provider "
                f"<addr> --cids {cids_arg}"
            )

        actual_addrs = host.get_addrs()
        logger.info(f"Provider node started with peer ID: {host.get_id()}")
        logger.info(
            f"Listening on: {actual_addrs[0] if actual_addrs else 'no addresses'}"
        )
        logger.info("To connect a client, use:")
        if actual_addrs:
            logger.info(
                f"  python bitswap.py --mode client --provider {actual_addrs[0]}"
            )
        logger.info("Press Ctrl+C to stop...")

        try:
            await trio.sleep_forever()
            # Keep server running
            # while True:
            #     await trio.sleep(5)
            #     logger.info(f"Provider has {block_store.size()} blocks available")
        except KeyboardInterrupt:
            logger.info("Shutting down provider...")
        finally:
            await bitswap.stop()


async def run_client(
    provider_addr: str,
    block_cids: list[str] | None = None,
    port: int = 0,
) -> None:
    """
    Run a Bitswap client that requests blocks.

    Args:
        provider_addr: Multiaddr of the provider node
        block_cids: List of block CIDs to request (as hex strings)
        port: Port to listen on (0 for random)

    """
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host()

    # Parse provider address
    try:
        provider_maddr = multiaddr.Multiaddr(provider_addr)
        provider_info = info_from_p2p_addr(provider_maddr)
    except Exception as e:
        logger.error(f"Failed to parse provider address '{provider_addr}': {e}")
        return

    async with host.run([listen_addr]), trio.open_nursery() as nursery:
        # Create Bitswap client
        block_store = MemoryBlockStore()
        bitswap = BitswapClient(host, block_store)
        bitswap.set_nursery(nursery)
        await bitswap.start()

        actual_addrs = host.get_addrs()
        logger.info(f"Client node started with peer ID: {host.get_id()}")
        logger.info(
            f"Listening on: {actual_addrs[0] if actual_addrs else 'no addresses'}"
        )

        # Connect to provider
        logger.info(f"Connecting to provider {provider_info.peer_id}...")
        await host.connect(provider_info)
        logger.info("Connected!")

        # Request blocks
        if block_cids:
            logger.info(f"Requesting {len(block_cids)} blocks...")
            for i, cid_hex in enumerate(block_cids):
                try:
                    cid = bytes.fromhex(cid_hex)
                    logger.info(f"Requesting block {i}: {cid.hex()[:16]}...")

                    data = await bitswap.get_block(
                        cid, provider_info.peer_id, timeout=10
                    )
                    logger.info(f"Received block {i}: {data[:50]!r}...")

                except Exception as e:
                    logger.error(f"Failed to get block {cid_hex[:16]}...: {e}")
        else:
            # Interactive mode - need CIDs from provider
            logger.info(
                "\nNo block CIDs provided. In interactive mode, you need to specify "
                "CIDs to request."
            )
            logger.info("Example usage:")
            logger.info(
                "  python bitswap.py --mode client --provider <addr> "
                "--cids <cid1> <cid2>"
            )
            logger.info("\nYou can get CIDs from the provider's output.")
            logger.info(
                "\nWaiting for manual block requests (press Ctrl+C to exit)..."
            )

        logger.info(f"\nClient now has {block_store.size()} blocks")
        logger.info("Press Ctrl+C to exit...")

        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down client...")
        finally:
            await bitswap.stop()


async def run_file_transfer_demo() -> None:
    """
    Run a complete file transfer demonstration with two nodes.
    """
    logger.info("=== Bitswap File Transfer Demo ===\n")

    # Create test file
    test_file = Path("test_file.txt")
    test_content = b"This is a test file for Bitswap demonstration.\n" * 100
    test_file.write_bytes(test_content)
    logger.info(f"Created test file: {test_file} ({len(test_content)} bytes)")

    async with trio.open_nursery() as nursery:
        # Start provider in background
        async def provider_task() -> None:
            try:
                await run_provider(port=4001, file_path=str(test_file))
            except KeyboardInterrupt:
                pass

        nursery.start_soon(provider_task)

        # Wait for provider to start
        await trio.sleep(2)

        # Note: In a real demo, you'd need to get the provider's address
        # For now, this is a placeholder showing the structure
        logger.info("\nDemo started! In a real scenario:")
        logger.info("1. Provider would start and print its address")
        logger.info("2. Client would connect using that address")
        logger.info("3. Blocks would be transferred")

        await trio.sleep(5)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bitswap file sharing example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run as provider with example blocks
  python bitswap.py --mode provider

  # Run as provider with a file
  python bitswap.py --mode provider --file myfile.txt

  # Run as client
  python bitswap.py --mode client --provider /ip4/127.0.0.1/tcp/4001/p2p/QmPeer...

  # Run as client requesting specific blocks (use CIDs from provider output)
  python bitswap.py --mode client --provider /ip4/... --cids abc123 def456

  # Run demo
  python bitswap.py --mode demo
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["provider", "client", "demo"],
        required=True,
        help="Mode to run in",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (default: random)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        help="Provider multiaddr (required for client mode)",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="File to share (provider mode only)",
    )
    parser.add_argument(
        "--cids",
        nargs="+",
        help="Block CIDs to request (hex strings, client mode only)",
    )

    args = parser.parse_args()

    try:
        if args.mode == "provider":
            trio.run(run_provider, args.port, args.file)
        elif args.mode == "client":
            if not args.provider:
                parser.error("--provider is required in client mode")
            trio.run(run_client, args.provider, args.cids, args.port)
        elif args.mode == "demo":
            trio.run(run_file_transfer_demo)
    except KeyboardInterrupt:
        logger.info("\nExiting...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

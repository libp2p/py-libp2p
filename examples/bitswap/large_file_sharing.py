#!/usr/bin/env python3
"""
Large File Sharing Example using Bitswap with Merkle DAG.

This example demonstrates sharing large files (>100 MB) using the MerkleDag
layer which automatically handles chunking, linking, and multi-block fetching.

Run provider (terminal 1):
    python examples/bitswap/large_file_sharing.py provider --file /path/to/large/file.mp4

Run client (terminal 2):
    python examples/bitswap/large_file_sharing.py client --peer <provider_address> --cid <file_cid> --output downloaded_file.mp4

Example:
    # Terminal 1 - Share a 500 MB video file
    $ python examples/bitswap/large_file_sharing.py provider --file movie.mp4
    Provider listening on: /ip4/127.0.0.1/tcp/55123/p2p/QmProvider...
    Adding file to DAG... (this may take a moment)
    File added! Root CID: 0122abcd...
    Chunking: 100.0% [500.0/500.0 MB]
    Share this with client:
      --peer /ip4/127.0.0.1/tcp/55123/p2p/QmProvider...
      --cid 0122abcd...

    # Terminal 2 - Download the file
    $ python examples/bitswap/large_file_sharing.py client \\
        --peer /ip4/127.0.0.1/tcp/55123/p2p/QmProvider... \\
        --cid 0122abcd... \\
        --output downloaded_movie.mp4
    Connecting to provider...
    Fetching file info...
    File size: 500.0 MB (1953 chunks)
    Downloading: 100.0% [500.0/500.0 MB]
    File saved to: downloaded_movie.mp4
    Verifying integrity... ✓

"""

import argparse
import logging
from pathlib import Path
import sys

# Add parent directory to path to import libp2p
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import multiaddr
import trio

from libp2p import new_host
from libp2p.bitswap import BitswapClient, MemoryBlockStore
from libp2p.bitswap.dag import MerkleDag
from libp2p.peer.peerinfo import info_from_p2p_addr

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def format_progress_bar(current: int, total: int, width: int = 40) -> str:
    """Create a progress bar string."""
    if total == 0:
        return "[" + "=" * width + "]"

    percent = current / total
    filled = int(width * percent)
    bar = "=" * filled + "-" * (width - filled)
    return f"[{bar}] {percent * 100:.1f}%"


async def run_provider(file_path: str, port: int = 0):
    """
    Run provider that shares a large file.

    Args:
        file_path: Path to file to share
        port: Port to listen on (0 for random)

    """
    logger.info(f"Starting provider for file: {file_path}")

    # Verify file exists
    if not Path(file_path).exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    file_size = Path(file_path).stat().st_size
    logger.info(f"File size: {format_size(file_size)}")

    # Create host
    host = new_host()

    # Start host
    async with host.run([f"/ip4/0.0.0.0/tcp/{port}"]):
        # Setup Bitswap and MerkleDag
        store = MemoryBlockStore()
        bitswap = BitswapClient(host, store)
        await bitswap.start()

        dag = MerkleDag(bitswap)

        # Print provider info
        addrs = host.get_addrs()
        print("\n" + "=" * 60)
        print("PROVIDER READY")
        print("=" * 60)
        for addr in addrs:
            print(f"Listening on: {addr}/p2p/{host.get_id()}")
        print("=" * 60)

        # Add file to DAG
        print(f"\nAdding file to DAG... (file size: {format_size(file_size)})")
        print("This may take a moment for large files...")

        # Progress tracking
        last_progress = [0]  # Use list for mutable state

        def progress_callback(current, total, status):
            # Only print every 5% to avoid spam
            percent = (current / total * 100) if total > 0 else 0
            if percent - last_progress[0] >= 5 or current == total:
                bar = format_progress_bar(current, total)
                print(
                    f"\r{status.capitalize()}: {bar} "
                    f"{format_size(current)}/{format_size(total)}",
                    end="",
                    flush=True,
                )
                last_progress[0] = percent

        root_cid = await dag.add_file(
            file_path,
            progress_callback=progress_callback,
        )
        print()  # New line after progress

        # Print sharing instructions
        print("\n" + "=" * 60)
        print("FILE ADDED TO DAG!")
        print("=" * 60)
        print(f"Root CID: {root_cid.hex()}")
        print("\nShare these with the client:")
        print(f"  --peer {addrs[0]}/p2p/{host.get_id()}")
        print(f"  --cid {root_cid.hex()}")
        print("=" * 60)

        # Keep running
        print("\nProvider is running. Press Ctrl+C to stop.")
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            print("\n\nShutting down provider...")
            await bitswap.stop()


async def run_client(
    peer_addr: str,
    cid_hex: str,
    output_path: str,
    timeout: float = 60.0,
):
    """
    Run client that fetches a large file.

    Args:
        peer_addr: Provider's multiaddr (with peer ID)
        cid_hex: Root CID of file to fetch (hex string)
        output_path: Path to save downloaded file
        timeout: Timeout per block in seconds

    """
    logger.info(f"Starting client to fetch: {cid_hex}")

    # Parse CID
    try:
        root_cid = bytes.fromhex(cid_hex)
    except ValueError:
        logger.error(f"Invalid CID hex string: {cid_hex}")
        sys.exit(1)

    # Parse peer address
    try:
        maddr = multiaddr.Multiaddr(peer_addr)
        peer_info = info_from_p2p_addr(maddr)
    except Exception as e:
        logger.error(f"Invalid peer address: {e}")
        sys.exit(1)

    # Create host
    host = new_host()

    # Start host
    async with host.run(["/ip4/0.0.0.0/tcp/0"]):
        # Setup Bitswap and MerkleDag
        store = MemoryBlockStore()
        bitswap = BitswapClient(host, store)
        await bitswap.start()

        dag = MerkleDag(bitswap)

        print("\n" + "=" * 60)
        print("CLIENT STARTED")
        print("=" * 60)

        # Connect to provider
        print(f"Connecting to provider: {peer_info.peer_id}...")
        try:
            await host.connect(peer_info)
            print("✓ Connected to provider")
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            sys.exit(1)

        # Get file info first
        print("\nFetching file metadata...")
        try:
            info = await dag.get_file_info(root_cid, peer_id=peer_info.peer_id)
            file_size = info["size"]
            num_chunks = info["chunks"]

            print("✓ File metadata received")
            print(f"  File size: {format_size(file_size)}")
            print(f"  Chunks: {num_chunks}")
        except Exception as e:
            logger.error(f"Failed to get file info: {e}")
            sys.exit(1)

        # Download file with progress
        print("\nDownloading file...")
        last_progress = [0]

        def progress_callback(current, total, status):
            # Print every 2% to show progress without spam
            percent = (current / total * 100) if total > 0 else 0
            if percent - last_progress[0] >= 2 or current == total:
                bar = format_progress_bar(current, total)
                print(
                    f"\r{status.capitalize()}: {bar} "
                    f"{format_size(current)}/{format_size(total)}",
                    end="",
                    flush=True,
                )
                last_progress[0] = percent

        try:
            file_data = await dag.fetch_file(
                root_cid,
                peer_id=peer_info.peer_id,
                timeout=timeout,
                progress_callback=progress_callback,
            )
            print()  # New line after progress
        except Exception as e:
            logger.error(f"\nFailed to fetch file: {e}")
            sys.exit(1)

        # Save to file
        print(f"\nSaving to: {output_path}")
        try:
            output_file = Path(output_path)
            output_file.write_bytes(file_data)
            print(f"✓ File saved ({format_size(len(file_data))})")
        except Exception as e:
            logger.error(f"Failed to save file: {e}")
            sys.exit(1)

        # Verify integrity
        print("\nVerifying integrity...")
        from libp2p.bitswap.cid import verify_cid

        # For chunked files, verify the root CID
        if num_chunks > 1:
            print("✓ Multi-chunk file fetched successfully")
        else:
            # Single chunk - direct verification
            if verify_cid(root_cid, file_data):
                print("✓ File integrity verified")
            else:
                logger.warning("⚠ File integrity check failed!")

        print("\n" + "=" * 60)
        print("DOWNLOAD COMPLETE!")
        print("=" * 60)
        print(f"File saved to: {output_path}")
        print(f"Size: {format_size(len(file_data))}")
        print("=" * 60)

        await bitswap.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Large file sharing with Bitswap + Merkle DAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    # Provider arguments
    provider_parser = subparsers.add_parser(
        "provider",
        help="Run as provider (share a file)",
    )
    provider_parser.add_argument(
        "--file",
        required=True,
        help="Path to file to share",
    )
    provider_parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (default: random)",
    )

    # Client arguments
    client_parser = subparsers.add_parser(
        "client",
        help="Run as client (fetch a file)",
    )
    client_parser.add_argument(
        "--peer",
        required=True,
        help="Provider's multiaddr (e.g., /ip4/127.0.0.1/tcp/55123/p2p/QmXXX...)",
    )
    client_parser.add_argument(
        "--cid",
        required=True,
        help="Root CID of file to fetch (hex string)",
    )
    client_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to save downloaded file",
    )
    client_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout per block in seconds (default: 60)",
    )

    # Debug flag
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Set log level
    if args.debug:
        logging.getLogger("libp2p").setLevel(logging.DEBUG)
        logging.getLogger(__name__).setLevel(logging.DEBUG)

    # Run appropriate mode
    if args.mode == "provider":
        trio.run(run_provider, args.file, args.port)
    elif args.mode == "client":
        trio.run(
            run_client,
            args.peer,
            args.cid,
            args.output,
            args.timeout,
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Simple example demonstrating rendezvous protocol usage.

This example shows how to:
1. Start a rendezvous service
2. Register a peer under a namespace
3. Discover other peers in the same namespace
"""

import argparse
import logging
from pathlib import Path
import sys
import traceback

# Add parent directory to path to import libp2p
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import multiaddr
import trio

from libp2p import new_host
from libp2p.discovery.rendezvous import (
    RendezvousDiscovery,
    RendezvousService,
    config,
)
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr

# Enable logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("libp2p.discovery.rendezvous").setLevel(logging.INFO)
logging.getLogger("libp2p").propagate = True

# Create logger for this example
logger = logging.getLogger("rendezvous_example")


async def run_rendezvous_server(port: int = 0):
    """Run a rendezvous server."""
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host()

    async with host.run([listen_addr]), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        # Start rendezvous service
        service = RendezvousService(host)

        actual_addrs = host.get_addrs()
        logger.info(f"Rendezvous server started with peer ID: {host.get_id()}")
        logger.info(
            f"Listening on: {actual_addrs[0] if actual_addrs else 'no addresses'}"
        )
        logger.info("To connect a client, use:")
        if actual_addrs:
            logger.info(
                f"  python rendezvous.py --mode client --address {actual_addrs[0]}"
            )
        logger.info("Press Ctrl+C to stop...")

        try:
            # Keep server running and print stats periodically
            while True:
                await trio.sleep(10)
                stats = service.get_namespace_stats()
                if stats:
                    logger.info(f"Namespace stats: {stats}")
                else:
                    logger.info("No active registrations")
        except KeyboardInterrupt:
            logger.info("Shutting down rendezvous server...")
        except Exception as e:
            logger.error(f"Unexpected error in server: {e}")
            raise


async def run_client_example(
    server_addr: str,
    namespace: str = config.DEFAULT_NAMESPACE,
    enable_refresh: bool = False,
    port: int = 0,
):
    """Run a client that registers and discovers peers."""
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    host = new_host()

    # Parse server address and extract peer info
    try:
        server_maddr = multiaddr.Multiaddr(server_addr)
        server_info = info_from_p2p_addr(server_maddr)
    except Exception as e:
        logger.error(f"Failed to parse server address '{server_addr}': {e}")
        return

    async with host.run([listen_addr]), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        # Connect to server
        try:
            await host.connect(server_info)
            logger.info(f"Connected to rendezvous server: {server_info.peer_id}")
            logger.info(f"Enable refresh: {enable_refresh}")
        except Exception as e:
            logger.error(f"Failed to connect to server: {e}")
            return

        # Create rendezvous discovery
        discovery = RendezvousDiscovery(host, server_info.peer_id, enable_refresh)

        # Run discovery service in background if refresh is enabled
        async with trio.open_nursery() as nursery:
            if enable_refresh:
                # Start the discovery service
                nursery.start_soon(discovery.run)
                logger.info(
                    "🔄 Refresh mode enabled - discovery service running in background"
                )

            try:
                logger.info(f"Client started with peer ID: {host.get_id()}")

                # Register under a namespace with optional auto-refresh
                logger.info(f"Registering in namespace '{namespace}'...")
                ttl = await discovery.advertise(namespace, ttl=config.DEFAULT_TTL)
                logger.info(f"✓ Registered with TTL {ttl}s")

                # Wait a moment for registration to propagate
                await trio.sleep(1)

                # Discover other peers
                logger.info(f"Discovering peers in namespace '{namespace}'...")
                peers: list[PeerInfo] = []
                async for peer in discovery.find_peers(namespace, limit=10):
                    peers.append(peer)
                    if peer.peer_id != host.get_id():
                        logger.info(f"  Found peer: {peer.peer_id}")
                    else:
                        logger.info(f"  Found self: {peer.peer_id}")

                logger.info(f"Total peers found: {len(peers)}")

                if len(peers) > 1:
                    logger.info("✓ Successfully discovered other peers!")
                else:
                    logger.info("No other peers found (only self)")

                # Keep running for demonstration
                if enable_refresh:
                    logger.info("Refresh mode: Registration will auto-refresh")
                    logger.info("Running for 2 minutes to demonstrate refresh...")
                    await trio.sleep(120)  # 2 minutes to see refresh in action
                else:
                    logger.info("Keeping registration active for 30 seconds...")
                    logger.info(
                        "Start another client instance to see peer discovery in action!"
                    )
                    await trio.sleep(30)

                # Unregister
                logger.info(f"Unregistering from namespace '{namespace}'...")
                await discovery.unregister(namespace)
                logger.info("✓ Unregistered successfully")

            except Exception as e:
                logger.error(f"Error: {e}")
                traceback.print_exc()
            finally:
                # Clean up refresh tasks
                try:
                    await discovery.close()
                except Exception as e:
                    logger.error(f"Error closing discovery service: {e}")


async def run(
    mode: str,
    address: str = "",
    namespace: str = config.DEFAULT_NAMESPACE,
    port: int = 0,
    enable_refresh: bool = False,
):
    """Main run function."""
    logger.debug(f"Starting in {mode} mode")
    logger.debug(
        f"Parameters: address={address}, namespace={namespace},"
        f"port={port}, refresh={enable_refresh}"
    )

    if mode == "server":
        logger.debug("Running in server mode")
        await run_rendezvous_server(port)
    elif mode == "client":
        if not address:
            logger.error("Please provide rendezvous server address")
            logger.error("Use --address flag with server multiaddr")
            return
        logger.debug("Running in client mode")
        await run_client_example(address, namespace, enable_refresh, port)
    else:
        logger.error(f"Unknown mode '{mode}'. Use 'server' or 'client'")
        logger.error("Available modes: server, client")


def main():
    """Main function to demonstrate usage."""
    description = """
    Rendezvous Protocol Example

    This example demonstrates the rendezvous protocol for peer discovery.
    The rendezvous protocol allows peers to register under namespaces and
    discover other peers in the same namespace.

    Usage:
    1. Start a rendezvous server:
       python rendezvous.py --mode server

    2. Start one or more clients (in separate terminals):
       python rendezvous.py --mode client <server_multiaddr>

    3. Enable automatic refresh for long-running clients:
       python rendezvous.py --mode client <server_multiaddr> --refresh

    Example server multiaddr: /ip4/127.0.0.1/tcp/12345/p2p/QmPeerID...

    Refresh mode automatically:
    - Re-registers the peer before TTL expires (at 80% of TTL)
    - Refreshes discovery cache when it gets stale
    """

    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--mode", choices=["server", "client"], help="Run as server or client"
    )

    parser.add_argument(
        "--address",
        nargs="?",
        default="",
        help="Server multiaddr (required for client mode)",
    )

    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=0,
        help="Port for server to listen on (default: random)",
    )

    parser.add_argument(
        "-n",
        "--namespace",
        type=str,
        default=config.DEFAULT_NAMESPACE,
        help=f"Namespace to register/discover in (default: {config.DEFAULT_NAMESPACE})",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        default=False,
        help="Enable automatic refresh for registration and discovery cache",
    )

    args = parser.parse_args()

    if args.verbose:
        # logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("libp2p.discovery.rendezvous").setLevel(logging.DEBUG)

    try:
        trio.run(run, args.mode, args.address, args.namespace, args.port, args.refresh)
    except KeyboardInterrupt:
        logger.info("Exiting...")


if __name__ == "__main__":
    main()

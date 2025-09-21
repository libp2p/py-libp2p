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
logging.basicConfig(level=logging.INFO)


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
        print(f"Rendezvous server started with peer ID: {host.get_id()}")
        print(f"Listening on: {actual_addrs[0] if actual_addrs else 'no addresses'}")
        print("\nTo connect a client, use:")
        if actual_addrs:
            print(f"  python rendezvous.py --mode client --address {actual_addrs[0]}")
        print("\nPress Ctrl+C to stop...")

        try:
            # Keep server running and print stats periodically
            while True:
                await trio.sleep(10)
                stats = service.get_namespace_stats()
                if stats:
                    print(f"Namespace stats: {stats}")
                else:
                    print("No active registrations")
        except KeyboardInterrupt:
            print("\nShutting down rendezvous server...")


async def run_client_example(
    server_addr: str,
    namespace: str = config.DEFAULT_NAMESPACE,
    enable_refresh: bool = True,
):
    """Run a client that registers and discovers peers."""
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")
    host = new_host()

    # Parse server address and extract peer info
    server_maddr = multiaddr.Multiaddr(server_addr)
    server_info = info_from_p2p_addr(server_maddr)

    async with host.run([listen_addr]), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        # Connect to server
        try:
            await host.connect(server_info)
            print(f"Connected to rendezvous server: {server_info.peer_id}")
            print("enable refresh:", enable_refresh)
        except Exception as e:
            print(f"Failed to connect to server: {e}")
            return

        # Create rendezvous discovery
        discovery = RendezvousDiscovery(
            host, server_info.peer_id, enable_refresh
        )

        # Run discovery service in background if refresh is enabled
        async with trio.open_nursery() as nursery:
            if enable_refresh:
                # Start the discovery service
                nursery.start_soon(discovery.run)
                print("🔄 Refresh mode enabled - discovery service running in background")
            
            try:
                print(f"Client started with peer ID: {host.get_id()}")

                # Register under a namespace with optional auto-refresh
                print(f"Registering in namespace '{namespace}'...")
                ttl = await discovery.advertise(namespace, ttl=config.DEFAULT_TTL)
                print(f"✓ Registered with TTL {ttl}s")

                # Wait a moment for registration to propagate
                await trio.sleep(1)

                # Discover other peers
                print(f"Discovering peers in namespace '{namespace}'...")
                peers: list[PeerInfo] = []
                async for peer in discovery.find_peers(namespace, limit=10):
                    peers.append(peer)
                    if peer.peer_id != host.get_id():
                        print(f"  Found peer: {peer.peer_id}")
                    else:
                        print(f"  Found self: {peer.peer_id}")

                print(f"Total peers found: {len(peers)}")

                if len(peers) > 1:
                    print("✓ Successfully discovered other peers!")
                else:
                    print("No other peers found (only self)")

                # Keep running for demonstration
                if enable_refresh:
                    print("\nRefresh mode: Registration will auto-refresh")
                    print("Running for 2 minutes to demonstrate refresh...")
                    await trio.sleep(120)  # 2 minutes to see refresh in action
                else:
                    print("\nKeeping registration active for 30 seconds...")
                    print("Start another client instance to see peer discovery in action!")
                    await trio.sleep(30)

                # Unregister
                print(f"Unregistering from namespace '{namespace}'...")
                await discovery.unregister(namespace)
                print("✓ Unregistered successfully")

            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                # Clean up refresh tasks
                await discovery.close()


async def run(
    mode: str,
    address: str = "",
    namespace: str = config.DEFAULT_NAMESPACE,
    port: int = 0,
    enable_refresh: bool = False,
):
    """Main run function."""
    if mode == "server":
        await run_rendezvous_server(port)
    elif mode == "client":
        if not address:
            print("Please provide rendezvous server address")
            return
        await run_client_example(address, namespace, enable_refresh)
    else:
        print("Unknown mode. Use 'server' or 'client'")


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
        help="Enable automatic refresh for registration and discovery cache",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        trio.run(run, args.mode, args.address, args.namespace, args.port, args.refresh)
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()

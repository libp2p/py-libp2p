#!/usr/bin/env python3
"""
Example demonstrating connection limits and pruning.

This example shows how to:
1. Configure connection limits on a host
2. Create multiple peer hosts
3. Observe connection limit behavior
4. Monitor connection counts and pruning
5. Handle connection limit exceeded scenarios

Note: This example uses multiple hosts on different ports to demonstrate
inbound connection limits.
"""

import contextlib
import logging
import secrets

import trio

from libp2p import new_host, new_swarm
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from libp2p.network.config import ConnectionConfig
from libp2p.peer.peerinfo import PeerInfo

# Note: We use default security (Noise) by not specifying sec_opt
# This ensures proper peer ID verification and handshake
from libp2p.utils.address_validation import get_available_interfaces

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_peer_host(port: int, name: str) -> tuple[BasicHost, int]:
    """Create a peer host listening on the given port."""
    # Create key pair
    key_pair = create_new_key_pair(secrets.token_bytes(32))

    # Get available interfaces for this port
    listen_addrs = get_available_interfaces(port)

    # Create host with default security (Noise) - no explicit sec_opt needed
    # This ensures proper peer ID verification and handshake
    host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)

    # Ensure the returned host is specifically a BasicHost
    if not isinstance(host, BasicHost):
        host = BasicHost(network=host.get_network())

    logger.info(f"Created peer {name} on port {port}")
    return host, port


async def example_basic_connection_limits() -> None:
    """Example of basic connection limits configuration."""
    logger.info("=" * 60)
    logger.info("Example: Basic Connection Limits")
    logger.info("=" * 60)

    # Create main host with low connection limit for demonstration
    connection_config = ConnectionConfig(
        max_connections=3,  # Very low limit for demo
        max_connections_per_peer=1,  # One connection per peer
    )

    # Create main host with default security (Noise)
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(9000)

    # Create swarm with connection_config, then create BasicHost from it
    # Using default security (Noise) by not specifying sec_opt
    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    logger.info(f"Main host created with peer ID: {main_host.get_id().pretty()}")
    logger.info(f"Max connections: {connection_config.max_connections}")
    logger.info(
        f"Max connections per peer: {connection_config.max_connections_per_peer}"
    )

    # Create peer hosts
    NUM_PEERS = 10
    peer_hosts = []

    # Create all peer hosts first
    for i in range(NUM_PEERS):
        port = 9001 + i  # Different ports for each peer
        peer_host, actual_port = await create_peer_host(port, f"Peer-{i + 1}")
        peer_hosts.append((peer_host, actual_port))

    # Use AsyncExitStack to manage all hosts
    async with contextlib.AsyncExitStack() as stack:
        # Start main host
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))

        # Start all peer hosts
        for peer_host, (_, port) in zip([p[0] for p in peer_hosts], peer_hosts):
            peer_listen_addrs = get_available_interfaces(port)
            await stack.enter_async_context(
                peer_host.run(listen_addrs=peer_listen_addrs)
            )

        async with trio.open_nursery():
            # Wait a bit for hosts to start
            await trio.sleep(2)

            # Get main host address
            main_addr = main_host.get_addrs()[0]
            main_peer_id = main_host.get_id()

            logger.info(f"Main host listening on: {main_addr}")

            # Attempt connections from peers to main host
            connected_count = 0
            logger.info(
                f"\nAttempting connections from {NUM_PEERS} peers to main host..."
            )

            for i, (peer_host, peer_port) in enumerate(peer_hosts):
                try:
                    # Create PeerInfo for main host
                    peer_info = PeerInfo(main_peer_id, [main_addr])

                    # Connect peer to main host
                    await peer_host.connect(peer_info)

                    # Check if connection was successful
                    if main_peer_id in peer_host.get_live_peers():
                        connected_count += 1
                        logger.info(f"✅ Peer-{i + 1} connected successfully")
                    else:
                        logger.info(
                            f"❌ Peer-{i + 1} connection failed (likely due to limits)"
                        )

                    # Small delay between connection attempts
                    await trio.sleep(0.1)

                except Exception as e:
                    logger.info(f"❌ Peer-{i + 1} connection failed: {e}")

            # Check final connection count on main host
            live_peers = main_host.get_live_peers()
            logger.info(f"\nFinal connection count: {len(live_peers)}")
            logger.info(f"Expected max: {connection_config.max_connections}")
            logger.info(f"Peers attempted to connect: {NUM_PEERS}")
            logger.info(f"Peers successfully connected: {connected_count}")

            # Show which peers are connected
            logger.info(f"Connected peers: {[p.pretty() for p in live_peers]}")

            # Clean shutdown
            logger.info("\nShutting down...")
            await trio.sleep(1)

        # Hosts are automatically closed by AsyncExitStack
        logger.info("Basic connection limits example completed\n")


async def example_connection_pruning() -> None:
    """Example demonstrating connection pruning behavior."""
    logger.info("=" * 60)
    logger.info("Example: Connection Pruning")
    logger.info("=" * 60)

    # Create main host with low connection limit
    connection_config = ConnectionConfig(
        max_connections=2,  # Low limit to trigger pruning
        max_connections_per_peer=1,
    )

    # Create main host with default security (Noise)
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(9010)

    # Create swarm with connection_config, then create BasicHost from it
    # Using default security (Noise) by not specifying sec_opt
    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    logger.info("Connection pruning behavior:")
    logger.info("  - When max_connections exceeded, connections are pruned")
    logger.info("  - Pruning priority: peer tag value → stream count → direction → age")
    logger.info("  - Connections in allow list never pruned")
    logger.info(f"  - Current max_connections: {connection_config.max_connections}")

    # Create all peer hosts first
    peer_hosts = []
    for i in range(5):
        port = 9011 + i
        peer_host, _ = await create_peer_host(port, f"PrunePeer-{i + 1}")
        peer_hosts.append(peer_host)

    # Use AsyncExitStack to manage all hosts
    async with contextlib.AsyncExitStack() as stack:
        # Start main host
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))

        # Start all peer hosts
        for i, peer_host in enumerate(peer_hosts):
            port = 9011 + i
            peer_listen_addrs = get_available_interfaces(port)
            await stack.enter_async_context(
                peer_host.run(listen_addrs=peer_listen_addrs)
            )

        await trio.sleep(2)

        async with trio.open_nursery():
            # Connect first 2 peers (should succeed, max_connections=2)
            main_addr = main_host.get_addrs()[0]
            main_peer_id = main_host.get_id()

            logger.info(
                "Connecting first 2 peers (should succeed, max_connections=2)..."
            )
            for i in range(2):
                try:
                    peer_info = PeerInfo(main_peer_id, [main_addr])
                    await peer_hosts[i].connect(peer_info)
                    logger.info(f"✅ PrunePeer-{i + 1} connected")
                    await trio.sleep(0.5)
                except Exception as e:
                    logger.info(f"❌ PrunePeer-{i + 1} connection failed: {e}")

            # Check current connections
            current_count = len(main_host.get_live_peers())
            logger.info(f"Current connections: {current_count} (max: 2)")

            # Connect 3rd peer (should trigger pruning or rejection)
            logger.info(
                "\nConnecting 3rd peer (should trigger pruning or rejection)..."
            )
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_hosts[2].connect(peer_info)
                logger.info("✅ PrunePeer-3 connected (pruning may have occurred)")
            except Exception as e:
                logger.info(
                    f"❌ PrunePeer-3 connection failed "
                    f"(expected if limit enforced): {e}"
                )

            # Check final connections
            final_count = len(main_host.get_live_peers())
            logger.info(
                f"Final connections after pruning attempt: {final_count} (max: 2)"
            )

            await trio.sleep(1)

        # Hosts are automatically closed by AsyncExitStack

    logger.info("Connection pruning example completed\n")


async def main() -> None:
    """Run the connection limits examples."""
    try:
        await example_basic_connection_limits()
        await example_connection_pruning()
        logger.info("All connection management examples completed successfully!")
    except Exception as e:
        logger.error(f"Example failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)

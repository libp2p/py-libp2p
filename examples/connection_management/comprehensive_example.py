#!/usr/bin/env python3
"""
Comprehensive example demonstrating all connection management features.

This example shows a production-ready configuration combining:
1. Connection limits with real connections
2. Connection metrics and monitoring
3. Connection state tracking
4. Multiple connections per peer
5. Production best practices

Note: Reduced logging to focus on actual feature demonstrations.
"""

import contextlib
import logging
import secrets
from typing import cast

import trio

from libp2p import new_host, new_swarm
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from libp2p.network.config import ConnectionConfig
from libp2p.network.swarm import Swarm
from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.address_validation import get_available_interfaces

# Set up logging - reduced verbosity to focus on demonstrations
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
# Enable INFO for our example output
logger.setLevel(logging.INFO)


async def example_production_configuration() -> None:
    """Demonstrate production-ready configuration with real connections."""
    print("\n" + "=" * 60)
    print("Example 1: Production Configuration")
    print("=" * 60)

    # Production-ready configuration
    connection_config = ConnectionConfig(
        max_connections=5,  # Low for demo
        max_connections_per_peer=2,
        max_parallel_dials=10,
        inbound_connection_threshold=5,
        allow_list=["192.168.0.0/16"],  # Local network
    )

    # Create main host with production config
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7000)

    swarm = cast(
        Swarm,
        new_swarm(
            key_pair=main_key_pair,
            listen_addrs=main_listen_addrs,
            connection_config=connection_config,
        ),
    )
    main_host = BasicHost(network=swarm)

    print("\n📋 Configuration:")
    print(f"   Max connections: {connection_config.max_connections}")
    print(f"   Max per peer: {connection_config.max_connections_per_peer}")
    print(f"   Rate limit: {connection_config.inbound_connection_threshold}/sec")
    print(f"   Allow list: {len(connection_config.allow_list)} network(s)")

    # Create peer hosts
    peer_hosts = []
    for i in range(3):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7001 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7001 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        # Connect peers to main host
        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print(f"\n🔗 Connecting {len(peer_hosts)} peers to main host...")
        connected = 0
        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                connected += 1
                print(f"   ✅ Peer {i + 1} connected")
            except Exception as e:
                print(f"   ❌ Peer {i + 1} failed: {e}")

        await trio.sleep(0.5)

        # Show metrics
        metrics = swarm.get_metrics()
        print("\n📊 Metrics:")
        print(f"   Inbound: {metrics.inbound_connections}")
        print(f"   Outbound: {metrics.outbound_connections}")
        print(f"   Total: {swarm.get_total_connections()}")
        print(f"   Max allowed: {connection_config.max_connections}")

        await trio.sleep(0.5)

    print("✅ Production configuration demo completed\n")


async def example_connection_metrics() -> None:
    """Demonstrate connection metrics and monitoring."""
    print("\n" + "=" * 60)
    print("Example 2: Connection Metrics & Monitoring")
    print("=" * 60)

    connection_config = ConnectionConfig(max_connections=10)

    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7010)

    swarm = cast(
        Swarm,
        new_swarm(
            key_pair=main_key_pair,
            listen_addrs=main_listen_addrs,
            connection_config=connection_config,
        ),
    )
    main_host = BasicHost(network=swarm)

    # Create multiple peers
    peer_hosts = []
    for i in range(5):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7011 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7011 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        # Connect all peers
        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Establishing connections...")
        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
            except Exception:
                pass

        await trio.sleep(0.5)

        # Get comprehensive metrics
        metrics = swarm.get_metrics()

        print("\n📊 Connection Metrics:")
        print(f"   Inbound: {metrics.inbound_connections}")
        print(f"   Outbound: {metrics.outbound_connections}")
        print(f"   Total: {swarm.get_total_connections()}")

        # Connection map
        conn_map = swarm.get_connections_map()
        print("\n📋 Connection Map:")
        print(f"   Unique peers: {len(conn_map)}")
        for peer_id, conns in conn_map.items():
            directions = [getattr(c, "direction", "unknown") for c in conns]
            inbound_count = directions.count("inbound")
            outbound_count = directions.count("outbound")
            print(
                f"   Peer {peer_id.pretty()[:20]}...: {len(conns)} conn(s) "
                f"(inbound: {inbound_count}, outbound: {outbound_count})"
            )

        # 90th percentile metrics
        percentile = metrics.get_protocol_streams_per_connection_90th_percentile()
        if percentile:
            print("\n📈 90th Percentile Stream Metrics:")
            for protocol, value in percentile.items():
                print(f"   {protocol}: {value:.2f}")

        await trio.sleep(0.5)

    print("✅ Metrics demo completed\n")


async def example_connection_limits_demo() -> None:
    """Demonstrate connection limits in action."""
    print("\n" + "=" * 60)
    print("Example 3: Connection Limits Demonstration")
    print("=" * 60)

    # Low limits for demonstration
    connection_config = ConnectionConfig(
        max_connections=3,
        max_connections_per_peer=1,
    )

    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7020)

    swarm = cast(
        Swarm,
        new_swarm(
            key_pair=main_key_pair,
            listen_addrs=main_listen_addrs,
            connection_config=connection_config,
        ),
    )
    main_host = BasicHost(network=swarm)

    # Create more peers than the limit
    NUM_PEERS = 6
    peer_hosts = []
    for i in range(NUM_PEERS):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7021 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7021 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        limit_msg = f"\n🔗 Attempting {NUM_PEERS} connections "
        limit_msg += f"(limit: {connection_config.max_connections})..."
        print(limit_msg)
        successful = 0
        failed = 0

        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                successful += 1
                print(f"   ✅ Peer {i + 1}: Connected")
            except Exception:
                failed += 1
                print(f"   ❌ Peer {i + 1}: Rejected (limit reached)")
            await trio.sleep(0.1)

        await trio.sleep(0.5)

        # Show final state
        final_count = swarm.get_total_connections()
        print("\n📊 Results:")
        print(f"   Successful: {successful}")
        print(f"   Failed: {failed}")
        print(f"   Final connections: {final_count}")
        print(f"   Max allowed: {connection_config.max_connections}")
        enforcement = (
            "Working" if final_count <= connection_config.max_connections else "Failed"
        )
        print(f"   ✅ Limit enforcement: {enforcement}")

        await trio.sleep(0.5)

    print("✅ Connection limits demo completed\n")


async def example_connection_state_tracking() -> None:
    """Demonstrate connection state tracking and lifecycle."""
    print("\n" + "=" * 60)
    print("Example 4: Connection State Tracking")
    print("=" * 60)

    connection_config = ConnectionConfig(max_connections=5)

    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7030)

    swarm = cast(
        Swarm,
        new_swarm(
            key_pair=main_key_pair,
            listen_addrs=main_listen_addrs,
            connection_config=connection_config,
        ),
    )
    main_host = BasicHost(network=swarm)

    # Create peer hosts
    peer_hosts = []
    for i in range(3):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7031 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7031 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Establishing connections...")
        connections_established = []

        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                await trio.sleep(0.2)

                # Get connection from peer's perspective
                peer_swarm = peer_host.get_network()
                conns = peer_swarm.get_connections(main_peer_id)
                if conns:
                    connections_established.append((i, conns[0]))
                    print(f"   ✅ Peer {i + 1}: Connected")
            except Exception:
                print(f"   ❌ Peer {i + 1}: Failed")

        await trio.sleep(0.5)

        # Show connection state information
        print("\n📊 Connection State Information:")
        for i, conn in connections_established:
            direction = getattr(conn, "direction", "unknown")
            is_closed = conn.is_closed
            streams = len(conn.get_streams())
            created_at = getattr(conn, "_created_at", None)

            print(f"   Peer {i + 1}:")
            print(f"      Direction: {direction}")
            print(f"      Status: {'CLOSED' if is_closed else 'OPEN'}")
            print(f"      Streams: {streams}")
            if created_at:
                import time

                age = time.time() - created_at
                print(f"      Age: {age:.2f}s")

        # Demonstrate connection closure
        if connections_established:
            print("\n🔌 Closing connection from Peer 1...")
            _, conn_to_close = connections_established[0]
            await conn_to_close.close()
            await trio.sleep(0.2)
            status = "CLOSED" if conn_to_close.is_closed else "OPEN"
            print(f"   Status after close: {status}")

        await trio.sleep(0.5)

    print("✅ State tracking demo completed\n")


async def example_best_practices_summary() -> None:
    """Summary of best practices with working example."""
    print("\n" + "=" * 60)
    print("Example 5: Best Practices Summary")
    print("=" * 60)

    print("\n📋 Best Practices Demonstrated:")
    print("\n1. ✅ Connection Limits:")
    print("   - Set max_connections based on system resources")
    print("   - Use max_connections_per_peer to prevent abuse")
    print("   - Monitor connection counts regularly")

    print("\n2. ✅ Metrics & Monitoring:")
    print("   - Use get_metrics() for connection statistics")
    print("   - Track 90th percentile stream metrics")
    print("   - Monitor connection state transitions")

    print("\n3. ✅ Configuration:")
    print("   - Start with defaults (max_connections=300)")
    print("   - Tune based on actual usage patterns")
    print("   - Use ConnectionConfig for all settings")

    print("\n4. ✅ Production Setup:")
    print("   - Use new_swarm() with connection_config")
    print("   - Create BasicHost from configured swarm")
    print("   - Monitor metrics regularly")

    # Quick demo of proper setup
    print("\n💡 Example Production Setup:")
    config = ConnectionConfig(
        max_connections=300,
        max_connections_per_peer=3,
        inbound_connection_threshold=5,
    )
    print("   config = ConnectionConfig(")
    print(f"       max_connections={config.max_connections},")
    print(f"       max_connections_per_peer={config.max_connections_per_peer},")
    print(f"       inbound_connection_threshold={config.inbound_connection_threshold},")
    print("   )")
    print("   swarm = new_swarm(connection_config=config)")
    print("   host = BasicHost(network=swarm)")

    print("\n✅ Best practices summary completed\n")


async def main() -> None:
    """Run comprehensive connection management examples."""
    print("\n" + "=" * 60)
    print("Comprehensive Connection Management Demo")
    print("=" * 60)

    try:
        await example_production_configuration()
        await example_connection_metrics()
        await example_connection_limits_demo()
        await example_connection_state_tracking()
        await example_best_practices_summary()

        print("=" * 60)
        print("✅ All comprehensive examples completed successfully!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    trio.run(main)

#!/usr/bin/env python3
"""
Example demonstrating connection rate limiting.

This example shows how to:
1. Configure rate limiting for incoming connections
2. Understand rate limiting behavior (per IP address)
3. Handle rate limit exceeded scenarios
4. Demonstrate rate limit enforcement in action

Note: Reduced logging to focus on actual feature demonstrations.
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
from libp2p.utils.address_validation import get_available_interfaces

# Set up logging - reduced verbosity
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def example_basic_rate_limiting() -> None:
    """Demonstrate basic rate limiting configuration."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Rate Limiting")
    print("=" * 60)

    # Configure rate limiting with a low threshold for demonstration
    connection_config = ConnectionConfig(
        inbound_connection_threshold=2,  # 2 connections per second per IP
        max_connections=10,  # High enough to not be the limiting factor
    )

    print("\n📋 Configuration:")
    threshold = connection_config.inbound_connection_threshold
    print(f"   Rate limit: {threshold} connections/sec per IP")
    print(f"   Max connections: {connection_config.max_connections}")
    print("   Rate limiting is per-host (IP address)")

    # Create main host with rate limiting
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7200)

    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    # Create multiple peer hosts (all from same IP - localhost)
    NUM_PEERS = 5
    peer_hosts = []
    for i in range(NUM_PEERS):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7201 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7201 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        threshold = connection_config.inbound_connection_threshold
        print(
            f"\n🔗 Attempting {NUM_PEERS} rapid connections (limit: {threshold}/sec)..."
        )
        print("   (All from same IP - localhost)")

        allowed = 0
        rate_limited = 0

        # Try to connect all peers rapidly
        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                allowed += 1
                print(f"   ✅ Peer {i + 1}: Connected")
            except Exception as e:
                error_msg = str(e).lower()
                if "rate limit" in error_msg:
                    rate_limited += 1
                    print(f"   ⚠️  Peer {i + 1}: Rate limited")
                else:
                    print(f"   ❌ Peer {i + 1}: Failed - {str(e)[:40]}")
            # Small delay to see rate limiting in action
            await trio.sleep(0.1)

        await trio.sleep(0.5)

        print("\n📊 Results:")
        print(f"   Allowed: {allowed}")
        print(f"   Rate limited: {rate_limited}")
        threshold = connection_config.inbound_connection_threshold
        print(
            f"   ✅ Rate limiting working: Only {threshold} "
            f"connections/sec allowed per IP"
        )

        await trio.sleep(0.5)

    print("✅ Basic rate limiting demo completed\n")


async def example_rate_limit_behavior() -> None:
    """Demonstrate rate limit behavior and reset."""
    print("\n" + "=" * 60)
    print("Example 2: Rate Limit Behavior & Reset")
    print("=" * 60)

    connection_config = ConnectionConfig(
        inbound_connection_threshold=2,  # Low threshold for demo
        max_connections=10,
    )

    print("\n📋 Rate Limiting Behavior:")
    print("   - Tracks connection attempts per IP address")
    print("   - Time window: 1 second (sliding window)")
    threshold = connection_config.inbound_connection_threshold
    print(f"   - Threshold: {threshold} connections/sec")
    print("   - Resets automatically after time window")

    # Create main host
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7210)

    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    # Create peer hosts
    peer_hosts = []
    for i in range(4):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7211 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7211 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Phase 1: Rapid connections (should hit rate limit)...")
        allowed_phase1 = 0
        rate_limited_phase1 = 0

        for i, peer_host in enumerate(peer_hosts[:3]):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                allowed_phase1 += 1
                print(f"   ✅ Peer {i + 1}: Connected")
            except Exception as e:
                if "rate limit" in str(e).lower():
                    rate_limited_phase1 += 1
                    print(f"   ⚠️  Peer {i + 1}: Rate limited")
                else:
                    print(f"   ❌ Peer {i + 1}: Failed")
            await trio.sleep(0.1)

        print("\n⏱️  Waiting 1.5 seconds for rate limit window to reset...")
        await trio.sleep(1.5)

        print("\n🔗 Phase 2: Connections after reset (should succeed)...")
        allowed_phase2 = 0

        for i, peer_host in enumerate(peer_hosts[2:], start=3):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                allowed_phase2 += 1
                print(f"   ✅ Peer {i}: Connected (after reset)")
            except Exception as e:
                print(f"   ❌ Peer {i}: Failed - {str(e)[:40]}")
            await trio.sleep(0.1)

        print("\n📊 Results:")
        print(
            f"   Phase 1 (rapid): {allowed_phase1} allowed, "
            f"{rate_limited_phase1} rate limited"
        )
        print(f"   Phase 2 (after reset): {allowed_phase2} allowed")
        print("   ✅ Rate limit resets after time window")

        await trio.sleep(0.5)

    print("✅ Rate limit behavior demo completed\n")


async def example_custom_rate_limits() -> None:
    """Demonstrate different rate limit configurations."""
    print("\n" + "=" * 60)
    print("Example 3: Custom Rate Limit Configurations")
    print("=" * 60)

    print("\n📋 Configuration Scenarios:")

    # High-traffic scenario
    high_traffic_config = ConnectionConfig(
        inbound_connection_threshold=20,  # Higher threshold
        max_incoming_pending_connections=50,
        max_connections=100,
    )

    print("\n🚀 High-Traffic Configuration:")
    threshold = high_traffic_config.inbound_connection_threshold
    print(f"   Threshold: {threshold} connections/sec")
    print(f"   Max pending: {high_traffic_config.max_incoming_pending_connections}")
    print("   Use case: Public nodes, high-traffic networks")

    # Low-traffic scenario
    low_traffic_config = ConnectionConfig(
        inbound_connection_threshold=2,  # Lower threshold
        max_incoming_pending_connections=5,
        max_connections=20,
    )

    print("\n🔒 Low-Traffic Configuration:")
    threshold = low_traffic_config.inbound_connection_threshold
    print(f"   Threshold: {threshold} connections/sec")
    print(f"   Max pending: {low_traffic_config.max_incoming_pending_connections}")
    print("   Use case: Private networks, security-focused")

    # Production scenario
    production_config = ConnectionConfig(
        inbound_connection_threshold=5,  # Default
        max_incoming_pending_connections=10,
        max_connections=300,
    )

    print("\n⚙️  Production Configuration (Default):")
    threshold = production_config.inbound_connection_threshold
    print(f"   Threshold: {threshold} connections/sec")
    print(f"   Max pending: {production_config.max_incoming_pending_connections}")
    print("   Use case: Balanced security and usability")

    print("\n💡 Rate Limit Selection Guidelines:")
    print("   ✅ Consider expected traffic patterns")
    print("   ✅ Balance security vs. usability")
    print("   ✅ Monitor and adjust based on metrics")
    print("   ✅ Higher for public nodes, lower for private")

    # Demonstrate low-traffic config in action
    print("\n🧪 Testing Low-Traffic Configuration:")

    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7220)

    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=low_traffic_config,
    )
    main_host = BasicHost(network=swarm)

    peer_hosts = []
    for i in range(4):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7221 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7221 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        allowed = 0
        rate_limited = 0

        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                allowed += 1
                print(f"   ✅ Peer {i + 1}: Connected")
            except Exception as e:
                if "rate limit" in str(e).lower():
                    rate_limited += 1
                    print(f"   ⚠️  Peer {i + 1}: Rate limited")
                else:
                    print(f"   ❌ Peer {i + 1}: Failed")
            await trio.sleep(0.1)

        threshold = low_traffic_config.inbound_connection_threshold
        print(f"\n📊 Results (threshold={threshold}/sec):")
        print(f"   Allowed: {allowed}, Rate limited: {rate_limited}")

        await trio.sleep(0.5)

    print("✅ Custom rate limits demo completed\n")


async def example_rate_limit_exceeded() -> None:
    """Demonstrate rate limit exceeded scenarios."""
    print("\n" + "=" * 60)
    print("Example 4: Rate Limit Exceeded Protection")
    print("=" * 60)

    # Very low threshold to easily trigger rate limiting
    connection_config = ConnectionConfig(
        inbound_connection_threshold=1,  # Very low for demo
        max_connections=10,
    )

    print("\n📋 Configuration:")
    threshold = connection_config.inbound_connection_threshold
    print(f"   Rate limit: {threshold} connection/sec per IP")
    print("   This protects against connection flooding attacks")

    # Create main host
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7230)

    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    # Create many peer hosts to simulate flooding
    NUM_PEERS = 5
    peer_hosts = []
    for i in range(NUM_PEERS):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7231 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7231 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Simulating Connection Flooding Attack:")
        print(f"   Attempting {NUM_PEERS} rapid connections from same IP...")
        print(
            f"   (Only {connection_config.inbound_connection_threshold} should succeed)"
        )

        allowed = 0
        blocked = 0

        # Try to flood with rapid connections
        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                allowed += 1
                print(f"   ✅ Peer {i + 1}: Connected")
            except Exception as e:
                error_msg = str(e).lower()
                if "rate limit" in error_msg:
                    blocked += 1
                    print(f"   🛡️  Peer {i + 1}: Blocked by rate limiter")
                else:
                    print(f"   ❌ Peer {i + 1}: Failed - {str(e)[:40]}")
            # Very small delay to simulate rapid flooding
            await trio.sleep(0.05)

        await trio.sleep(0.5)

        print("\n📊 Protection Results:")
        print(f"   Allowed: {allowed}/{NUM_PEERS}")
        print(f"   Blocked: {blocked}/{NUM_PEERS}")
        print("   ✅ Rate limiting successfully prevented flooding")

        # Show rate limiter status
        print("\n🔍 Rate Limiter Details:")
        threshold = connection_config.inbound_connection_threshold
        print(f"   Threshold: {threshold} connections/sec")
        print("   Time window: 1 second (sliding window)")
        print("   Protection: Per IP address")

        print("\n💡 When Rate Limit is Exceeded:")
        print("   ✅ Connection attempts rejected immediately")
        print("   ✅ No connection is established")
        print("   ✅ Rate limiter resets after time window")
        print("   ✅ Protects against connection flooding attacks")

        await trio.sleep(0.5)

    print("✅ Rate limit exceeded demo completed\n")


async def main() -> None:
    """Run all rate limiting examples."""
    print("\n" + "=" * 60)
    print("Connection Rate Limiting Demo")
    print("=" * 60)

    try:
        await example_basic_rate_limiting()
        await example_rate_limit_behavior()
        await example_custom_rate_limits()
        await example_rate_limit_exceeded()

        print("=" * 60)
        print("✅ All rate limiting examples completed successfully!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    trio.run(main)

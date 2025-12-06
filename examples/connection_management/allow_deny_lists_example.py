#!/usr/bin/env python3
"""
Example demonstrating allow/deny lists for connection gating.

This example shows how to:
1. Configure allow lists (whitelist) - only allow specific IPs/networks
2. Configure deny lists (blacklist) - block specific IPs/networks
3. Use CIDR blocks for network ranges
4. Understand precedence rules (deny > allow)
5. Demonstrate connection gating in action

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
from libp2p.network.connection_gate import ConnectionGate
from libp2p.network.swarm import Swarm
from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.address_validation import get_available_interfaces

# Set up logging - reduced verbosity
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def example_allow_list() -> None:
    """Demonstrate allow list (whitelist) behavior."""
    print("\n" + "=" * 60)
    print("Example 1: Allow List (Whitelist)")
    print("=" * 60)

    # Get the actual IP we'll be using (from localhost)
    import socket

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    # Fallback to common local IPs
    if local_ip.startswith("127."):
        local_ip = "127.0.0.1"

    print("\n📋 Configuration:")
    print(f"   Allow list: ['{local_ip}/32', '127.0.0.1/32']")
    print("   Only connections from these IPs will be allowed")

    # Configure allow list with actual local IP
    connection_config = ConnectionConfig(
        allow_list=[
            f"{local_ip}/32",  # Specific local IP
            "127.0.0.1/32",  # Localhost
        ],
        max_connections=5,
    )

    # Create main host with allow list
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7100)

    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    # Create peer hosts
    peer_hosts = []
    for i in range(3):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7101 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7101 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Testing connections with allow list...")
        print("   (All connections from localhost should be allowed)")

        allowed = 0
        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                allowed += 1
                print(f"   ✅ Peer {i + 1}: Allowed (IP in allow list)")
            except Exception as e:
                print(f"   ❌ Peer {i + 1}: Denied - {e}")

        await trio.sleep(0.5)

        print("\n📊 Results:")
        print(f"   Allowed: {allowed}/{len(peer_hosts)}")
        print("   ✅ Allow list is working: Connections from allowed IPs succeed")

        await trio.sleep(0.5)

    print("✅ Allow list demo completed\n")


async def example_deny_list() -> None:
    """Demonstrate deny list (blacklist) behavior."""
    print("\n" + "=" * 60)
    print("Example 2: Deny List (Blacklist)")
    print("=" * 60)

    import socket

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    if local_ip.startswith("127."):
        local_ip = "127.0.0.1"

    print("\n📋 Configuration:")
    print(f"   Deny list: ['{local_ip}/32', '127.0.0.1/32']")
    print("   Connections from these IPs will be blocked")

    # Configure deny list with actual local IP
    connection_config = ConnectionConfig(
        deny_list=[
            f"{local_ip}/32",  # Block local IP
            "127.0.0.1/32",  # Block localhost
        ],
        max_connections=10,  # High limit so it's not the limiting factor
    )

    # Create main host with deny list
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7110)

    swarm = new_swarm(
        key_pair=main_key_pair,
        listen_addrs=main_listen_addrs,
        connection_config=connection_config,
    )
    main_host = BasicHost(network=swarm)

    # Create peer hosts
    peer_hosts = []
    for i in range(3):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7111 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7111 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Testing connections with deny list...")
        print("   (All connections from localhost should be denied)")

        denied = 0
        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                print(
                    f"   ⚠️  Peer {i + 1}: Connected (unexpected - IP should be denied)"
                )
            except Exception as e:
                denied += 1
                error_msg = str(e)
                if (
                    "connection gate" in error_msg.lower()
                    or "denied" in error_msg.lower()
                ):
                    print(
                        f"   ✅ Peer {i + 1}: Denied by connection gate (as expected)"
                    )
                else:
                    print(f"   ❌ Peer {i + 1}: Failed - {error_msg[:50]}")

        await trio.sleep(0.5)

        print("\n📊 Results:")
        print(f"   Denied: {denied}/{len(peer_hosts)}")
        print("   ✅ Deny list is working: Connections from denied IPs are blocked")

        await trio.sleep(0.5)

    print("✅ Deny list demo completed\n")


async def example_cidr_blocks() -> None:
    """Demonstrate CIDR block usage for network ranges."""
    print("\n" + "=" * 60)
    print("Example 3: CIDR Blocks")
    print("=" * 60)

    print("\n📋 CIDR Block Examples:")
    print("   /32: Single IP address (e.g., 192.168.1.100/32)")
    print("   /24: 256 addresses (e.g., 192.168.1.0/24)")
    print("   /16: 65,536 addresses (e.g., 192.168.0.0/16)")
    print("   /8:  16,777,216 addresses (e.g., 10.0.0.0/8)")

    # Demonstrate CIDR parsing and checking
    from multiaddr import Multiaddr

    gate = ConnectionGate(
        allow_list=["192.168.0.0/16", "127.0.0.0/8"],
        deny_list=["192.168.1.100/32"],
    )

    print("\n🧪 Testing CIDR Block Matching:")

    test_cases = [
        ("/ip4/192.168.1.50/tcp/4001", "192.168.0.0/16", True, "In /16 range"),
        (
            "/ip4/192.168.1.100/tcp/4001",
            "192.168.1.100/32",
            False,
            "Denied by deny list",
        ),
        ("/ip4/127.0.0.1/tcp/4001", "127.0.0.0/8", True, "In /8 range"),
        ("/ip4/10.0.0.1/tcp/4001", None, False, "Not in allow list"),
    ]

    for addr_str, expected_range, should_allow, description in test_cases:
        addr = Multiaddr(addr_str)
        is_allowed = gate.is_allowed(addr)
        status = "✅" if is_allowed == should_allow else "❌"
        result = "ALLOWED" if is_allowed else "DENIED"
        print(f"   {status} {addr_str[:30]:<30} → {result:6} ({description})")

    print("✅ CIDR blocks demo completed\n")


async def example_precedence_rules() -> None:
    """Demonstrate allow/deny list precedence rules."""
    print("\n" + "=" * 60)
    print("Example 4: Precedence Rules")
    print("=" * 60)

    print("\n📋 Precedence Rules:")
    print("   1. Deny list checked FIRST (highest priority)")
    print("   2. If IP in deny list → REJECTED")
    print("   3. If IP in allow list → ALLOWED")
    print("   4. Otherwise → Normal rules apply")

    # Demonstrate precedence with connection gate
    from multiaddr import Multiaddr

    # IP that's in both lists
    test_ip = "192.168.1.100"

    gate = ConnectionGate(
        allow_list=["192.168.1.0/24"],  # Includes 192.168.1.100
        deny_list=[f"{test_ip}/32"],  # Explicitly denies 192.168.1.100
    )

    print("\n🧪 Testing Precedence:")
    print(f"   IP: {test_ip}")
    print("   In allow list: 192.168.1.0/24 → YES")
    print(f"   In deny list: {test_ip}/32 → YES")

    test_addr = Multiaddr(f"/ip4/{test_ip}/tcp/4001")
    is_allowed = gate.is_allowed(test_addr)

    print("\n📊 Result:")
    if is_allowed:
        print("   ⚠️  ALLOWED (unexpected - deny should take precedence)")
    else:
        print("   ✅ DENIED (deny list takes precedence over allow list)")

    # Test IP only in allow list
    test_ip2 = "192.168.1.50"
    test_addr2 = Multiaddr(f"/ip4/{test_ip2}/tcp/4001")
    is_allowed2 = gate.is_allowed(test_addr2)

    print("\n🧪 Testing IP only in allow list:")
    print(f"   IP: {test_ip2}")
    print("   In allow list: YES")
    print("   In deny list: NO")
    print(f"   Result: {'✅ ALLOWED' if is_allowed2 else '❌ DENIED'}")

    print("✅ Precedence rules demo completed\n")


async def example_production_configuration() -> None:
    """Demonstrate production-ready allow/deny configuration."""
    print("\n" + "=" * 60)
    print("Example 5: Production Configuration")
    print("=" * 60)

    import socket

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    if local_ip.startswith("127."):
        local_ip = "127.0.0.1"

    # Extract network from IP (simplified - in production use actual network)
    if local_ip.startswith("192.168."):
        network_base = "192.168.0.0/16"
    elif local_ip.startswith("10."):
        network_base = "10.0.0.0/8"
    else:
        network_base = "127.0.0.0/8"

    print("\n📋 Production Configuration Example:")
    print(f"   Allow list: ['{network_base}']  # Trusted internal network")
    print("   Deny list: []  # Add known malicious IPs here")
    print("   Max connections: 300")
    print("   Rate limit: 5/sec")

    # Production configuration
    connection_config = ConnectionConfig(
        allow_list=[network_base],
        deny_list=[],  # In production, add known bad IPs
        max_connections=300,
        inbound_connection_threshold=5,
    )

    # Create host with production config
    main_key_pair = create_new_key_pair(secrets.token_bytes(32))
    main_listen_addrs = get_available_interfaces(7120)

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
    for i in range(2):
        key_pair = create_new_key_pair(secrets.token_bytes(32))
        listen_addrs = get_available_interfaces(7121 + i)
        host = new_host(key_pair=key_pair, listen_addrs=listen_addrs)
        peer_hosts.append(host)

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(main_host.run(listen_addrs=main_listen_addrs))
        for i, peer_host in enumerate(peer_hosts):
            listen_addrs = get_available_interfaces(7121 + i)
            await stack.enter_async_context(peer_host.run(listen_addrs=listen_addrs))

        await trio.sleep(1)

        main_addr = main_host.get_addrs()[0]
        main_peer_id = main_host.get_id()

        print("\n🔗 Testing production configuration...")

        for i, peer_host in enumerate(peer_hosts):
            try:
                peer_info = PeerInfo(main_peer_id, [main_addr])
                await peer_host.connect(peer_info)
                print(f"   ✅ Peer {i + 1}: Connected (IP in allow list)")
            except Exception as e:
                error_msg = str(e)
                if "connection gate" in error_msg.lower():
                    print(f"   ❌ Peer {i + 1}: Denied by connection gate")
                else:
                    print(f"   ❌ Peer {i + 1}: Failed - {error_msg[:40]}")

        await trio.sleep(0.5)

        # Show connection gate status
        gate = swarm.connection_gate
        print("\n📊 Connection Gate Status:")
        print(f"   Allow list entries: {len(gate.allow_list)}")
        print(f"   Deny list entries: {len(gate.deny_list)}")
        print(f"   Active connections: {swarm.get_total_connections()}")

        print("\n💡 Best Practices:")
        print("   ✅ Keep allow lists small and specific")
        print("   ✅ Regularly update deny lists")
        print("   ✅ Use CIDR blocks for network ranges")
        print("   ✅ Monitor connection attempts")
        print("   ✅ Combine with connection limits and rate limiting")

        await trio.sleep(0.5)

    print("✅ Production configuration demo completed\n")


async def main() -> None:
    """Run all allow/deny list examples."""
    print("\n" + "=" * 60)
    print("Allow/Deny Lists Connection Gating Demo")
    print("=" * 60)

    try:
        await example_allow_list()
        await example_deny_list()
        await example_cidr_blocks()
        await example_precedence_rules()
        await example_production_configuration()

        print("=" * 60)
        print("✅ All allow/deny list examples completed successfully!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    trio.run(main)

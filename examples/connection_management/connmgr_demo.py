"""
Connection Manager Demo - Demonstrates Auto-Connection and Pruning

This example demonstrates the advanced connection management features in py-libp2p:
1. Automatic connection when below low_watermark
2. Automatic pruning when above high_watermark
3. Connection tagging to influence pruning decisions
4. Peer protection to prevent pruning

The example creates 3 hosts and demonstrates:
- How connections are automatically pruned when exceeding high_watermark
- How connections are automatically established when below low_watermark
- How tagged peers are preserved during pruning
- How protected peers are never pruned

Usage:
    python -m examples.connection_management.connmgr_demo

Reference:
- go-libp2p ConnManager: https://pkg.go.dev/github.com/libp2p/go-libp2p/core/connmgr
"""

import logging
import secrets
import sys
import traceback

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.config import ConnectionConfig
from libp2p.network.tag_store import CommonTags
from libp2p.peer.peerinfo import PeerInfo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_PORT = 12000


def create_host_with_config(port: int, config: ConnectionConfig | None = None):
    """Create a new host with optional connection configuration."""
    key_pair = create_new_key_pair(secrets.token_bytes(32))
    return new_host(key_pair=key_pair, connection_config=config)


async def demo_basic_connection_management():
    """
    Demonstrate basic connection management with 3 hosts.

    Shows how connections are tracked and how to use the connection manager
    to get connection information.
    """
    print("\n" + "=" * 70)
    print("  Demo 1: Basic Connection Management")
    print("=" * 70)

    # Create three hosts with default config
    host_a = create_host_with_config(BASE_PORT)
    host_b = create_host_with_config(BASE_PORT + 1)
    host_c = create_host_with_config(BASE_PORT + 2)

    print(f"\n  Host A: {str(host_a.get_id())[:20]}...")
    print(f"  Host B: {str(host_b.get_id())[:20]}...")
    print(f"  Host C: {str(host_c.get_id())[:20]}...")

    addr_a = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT}")]
    addr_b = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 1}")]
    addr_c = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 2}")]

    async with (
        host_a.run(listen_addrs=addr_a),
        host_b.run(listen_addrs=addr_b),
        host_c.run(listen_addrs=addr_c),
    ):
        print("\n  ✅ All hosts started!")

        # Get swarm for connection management
        swarm_a = host_a.get_network()

        # Show initial connection count
        print(f"\n  Initial connections: {swarm_a.get_total_connections()}")

        # Connect Host A to Host B
        print("\n  Connecting Host A to Host B...")
        await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))
        print(f"  ✅ Connected! Total connections: {swarm_a.get_total_connections()}")

        # Connect Host A to Host C
        print("\n  Connecting Host A to Host C...")
        await host_a.connect(PeerInfo(host_c.get_id(), host_c.get_addrs()))
        print(f"  ✅ Connected! Total connections: {swarm_a.get_total_connections()}")

        # Show connection details
        print("\n  --- Connection Details ---")
        for peer_id, conns in swarm_a.get_connections_map().items():
            print(f"  Peer {str(peer_id)[:20]}...: {len(conns)} connection(s)")

        # Get metrics
        metrics = swarm_a.get_metrics()
        print("\n  Connection Metrics:")
        print(f"    Inbound: {metrics['inbound']}")
        print(f"    Outbound: {metrics['outbound']}")
        print(f"    Total: {metrics['total']}")
        print(f"    Peers: {metrics['peers']}")

        print("\n  ✅ Basic connection management demo complete!")


async def demo_connection_gate():
    """
    Demonstrate ConnectionGate - IP Allow/Deny Lists.

    Shows how to use ConnectionGate to control which IPs can connect
    using allow lists and deny lists with real hosts.
    """
    print("\n" + "=" * 70)
    print("  Demo 2: ConnectionGate - IP Allow/Deny Lists")
    print("=" * 70)

    # Create Host A (normal host - will be the one trying to connect)
    host_a = create_host_with_config(BASE_PORT + 5)
    host_a_ip = "127.0.0.1"
    addr_a = [multiaddr.Multiaddr(f"/ip4/{host_a_ip}/tcp/{BASE_PORT + 5}")]

    # Create Host B with deny_list blocking Host A's IP
    config_deny = ConnectionConfig(
        deny_list=[host_a_ip],  # Block 127.0.0.1
    )
    host_b = create_host_with_config(BASE_PORT + 6, config_deny)
    addr_b = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 6}")]

    # Create Host C with allow_list only allowing Host A's IP
    config_allow = ConnectionConfig(
        allow_list=[host_a_ip],  # Only allow 127.0.0.1
    )
    host_c = create_host_with_config(BASE_PORT + 7, config_allow)
    addr_c = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 7}")]

    print(f"\n  Host A (connector): {str(host_a.get_id())[:20]}...")
    print(f"    Address: {host_a_ip}")
    print(f"\n  Host B (deny_list=['{host_a_ip}']): {str(host_b.get_id())[:20]}...")
    print("    → Will BLOCK connections from Host A")
    print(f"\n  Host C (allow_list=['{host_a_ip}']): {str(host_c.get_id())[:20]}...")
    print("    → Will ALLOW connections from Host A")

    async with (
        host_a.run(listen_addrs=addr_a),
        host_b.run(listen_addrs=addr_b),
        host_c.run(listen_addrs=addr_c),
    ):
        print("\n  ✅ All hosts started!")

        # Test 1: Host A tries to connect to Host B (should be BLOCKED)
        print("\n  --- Test 1: Host A → Host B (deny_list blocks Host A) ---")
        print(f"    Host A ({host_a_ip}) connecting to Host B...", end=" ")
        try:
            await host_a.connect(PeerInfo(host_b.get_id(), addr_b))
            # If we get here, connection succeeded
            # (may happen due to outbound not being blocked)
            swarm_b = host_b.get_network()
            print("Connected (outbound dial succeeded)")
            print("    Note: deny_list blocks INBOUND connections, not outbound dials")
            print(f"    Host B connections: {swarm_b.get_total_connections()}")
        except Exception as e:
            print("❌ BLOCKED!")
            print(f"    Reason: {type(e).__name__}")

        # Test 2: Host A tries to connect to Host C (should SUCCEED)
        print("\n  --- Test 2: Host A → Host C (allow_list allows Host A) ---")
        print(f"    Host A ({host_a_ip}) connecting to Host C...", end=" ")
        try:
            await host_a.connect(PeerInfo(host_c.get_id(), addr_c))
            print("✅ ALLOWED!")
            swarm_c = host_c.get_network()
            print(f"    Host C connections: {swarm_c.get_total_connections()}")
        except Exception as e:
            print(f"❌ Failed: {e}")

        # Test 3: Demonstrate the gate's filtering logic directly
        print("\n  --- Test 3: ConnectionGate Filter Logic ---")
        swarm_b = host_b.get_network()
        swarm_c = host_c.get_network()

        test_addr = multiaddr.Multiaddr(f"/ip4/{host_a_ip}/tcp/1234")
        print(f"    Testing address: {test_addr}")
        is_allowed_b = swarm_b.connection_gate.is_allowed(test_addr)
        status_b = "❌ DENIED" if not is_allowed_b else "✅ ALLOWED"
        print(f"    Host B gate (deny_list): {status_b}")
        is_allowed_c = swarm_c.connection_gate.is_allowed(test_addr)
        status_c = "✅ ALLOWED" if is_allowed_c else "❌ DENIED"
        print(f"    Host C gate (allow_list): {status_c}")

        # Test with a different IP
        other_addr = multiaddr.Multiaddr("/ip4/192.168.1.50/tcp/1234")
        print(f"\n    Testing address: {other_addr}")
        is_allowed_b = swarm_b.connection_gate.is_allowed(other_addr)
        status_b = "❌ DENIED" if not is_allowed_b else "✅ ALLOWED"
        print(f"    Host B gate (deny_list): {status_b}")
        is_allowed_c = swarm_c.connection_gate.is_allowed(other_addr)
        status_c = "✅ ALLOWED" if is_allowed_c else "❌ DENIED"
        print(f"    Host C gate (allow_list): {status_c}")

    print("\n  ✅ ConnectionGate demo complete!")


async def demo_tagging_and_protection():
    """
    Demonstrate connection tagging and protection.

    Shows how tags affect pruning priority and how protected peers
    are never pruned.
    """
    print("\n" + "=" * 70)
    print("  Demo 3: Tagging and Protection")
    print("=" * 70)

    # Create hosts
    host_server = create_host_with_config(BASE_PORT + 10)
    host_important = create_host_with_config(BASE_PORT + 11)
    host_normal = create_host_with_config(BASE_PORT + 12)
    host_low = create_host_with_config(BASE_PORT + 13)

    addr_server = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 10}")]
    addr_important = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 11}")]
    addr_normal = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 12}")]
    addr_low = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 13}")]

    async with (
        host_server.run(listen_addrs=addr_server),
        host_important.run(listen_addrs=addr_important),
        host_normal.run(listen_addrs=addr_normal),
        host_low.run(listen_addrs=addr_low),
    ):
        print("\n  ✅ All hosts started!")

        swarm = host_server.get_network()

        # Connect all peers to server
        await host_important.connect(
            PeerInfo(host_server.get_id(), host_server.get_addrs())
        )
        await host_normal.connect(
            PeerInfo(host_server.get_id(), host_server.get_addrs())
        )
        await host_low.connect(PeerInfo(host_server.get_id(), host_server.get_addrs()))

        print(f"\n  Connected {swarm.get_total_connections()} peers to server")

        # Tag peers with different importance levels
        print("\n  --- Tagging Peers ---")

        # Important peer: high tag values
        swarm.tag_peer(host_important.get_id(), CommonTags.DHT, 500)
        swarm.tag_peer(host_important.get_id(), CommonTags.RELAY, 300)
        print("  Important peer tagged with DHT=500, RELAY=300")

        # Normal peer: medium tag values
        swarm.tag_peer(host_normal.get_id(), CommonTags.APPLICATION, 100)
        print("  Normal peer tagged with APPLICATION=100")

        # Low peer: low tag values
        swarm.tag_peer(host_low.get_id(), CommonTags.APPLICATION, 10)
        print("  Low peer tagged with APPLICATION=10")

        # Show tag values
        print("\n  --- Tag Values ---")
        peers = [
            host_important.get_id(),
            host_normal.get_id(),
            host_low.get_id(),
        ]
        for peer_id in peers:
            tag_info = swarm.get_tag_info(peer_id)
            value = tag_info.value if tag_info else 0
            protected = swarm.is_protected(peer_id)
            peer_short = str(peer_id)[:20]
            print(f"  Peer {peer_short}...: value={value}, protected={protected}")

        # Protect the important peer
        print("\n  --- Protection ---")
        swarm.protect(host_important.get_id(), "critical-service")
        print("  ✅ Protected important peer with tag 'critical-service'")
        is_protected = swarm.is_protected(host_important.get_id())
        print(f"  Is important peer protected? {is_protected}")

        # Explain pruning order
        print("\n  --- Pruning Priority (if triggered) ---")
        print("  1. Low peer (tag=10) - would be pruned first")
        print("  2. Normal peer (tag=100) - would be pruned second")
        print("  3. Important peer - PROTECTED, never pruned!")

        print("\n  ✅ Tagging and protection demo complete!")


async def demo_watermarks():
    """
    Demonstrate low and high watermark behavior.

    Shows how the connection manager:
    - Prunes connections when above high_watermark
    - Auto-connects when below low_watermark
    """
    print("\n" + "=" * 70)
    print("  Demo 4: Watermarks Configuration")
    print("=" * 70)

    # Create a host with custom watermark configuration
    # Using very small values for demonstration
    config = ConnectionConfig(
        min_connections=1,
        low_watermark=2,
        high_watermark=3,
        max_connections=5,
        auto_connect_interval=5.0,  # Check every 5 seconds
        grace_period=2.0,
    )

    print("\n  Custom Configuration:")
    print(f"    min_connections: {config.min_connections}")
    print(f"    low_watermark: {config.low_watermark}")
    print(f"    high_watermark: {config.high_watermark}")
    print(f"    max_connections: {config.max_connections}")

    host_main = create_host_with_config(BASE_PORT + 20, config)
    host_1 = create_host_with_config(BASE_PORT + 21)
    host_2 = create_host_with_config(BASE_PORT + 22)
    host_3 = create_host_with_config(BASE_PORT + 23)
    host_4 = create_host_with_config(BASE_PORT + 24)

    addr_main = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 20}")]
    addr_1 = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 21}")]
    addr_2 = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 22}")]
    addr_3 = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 23}")]
    addr_4 = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 24}")]

    async with (
        host_main.run(listen_addrs=addr_main),
        host_1.run(listen_addrs=addr_1),
        host_2.run(listen_addrs=addr_2),
        host_3.run(listen_addrs=addr_3),
        host_4.run(listen_addrs=addr_4),
    ):
        print("\n  ✅ All hosts started!")

        swarm = host_main.get_network()

        # Step 1: Connect to 2 peers (below high_watermark)
        print("\n  --- Step 1: Connect to 2 peers (below high_watermark of 3) ---")
        # Use explicit addresses to ensure correct connectivity
        await host_main.connect(PeerInfo(host_1.get_id(), addr_1))
        await host_main.connect(PeerInfo(host_2.get_id(), addr_2))
        print(f"  Connections: {swarm.get_total_connections()} (high_watermark=3)")
        print("  ✅ No pruning needed - below high_watermark")

        # Wait a bit
        await trio.sleep(0.5)

        # Step 2: Connect to more peers (above high_watermark)
        print("\n  --- Step 2: Connect to 2 more peers (exceeds high_watermark) ---")
        print("  Note: Auto-pruning happens immediately when exceeding high_watermark")
        # Use explicit addresses instead of get_addrs() to ensure correct addresses
        await host_main.connect(PeerInfo(host_3.get_id(), addr_3))
        conn_count = swarm.get_total_connections()
        print(f"  After connecting to peer 3: {conn_count} connections")
        print(f"    (at high_watermark={config.high_watermark}, no pruning yet)")

        await host_main.connect(PeerInfo(host_4.get_id(), addr_4))
        conn_count = swarm.get_total_connections()
        print(f"  After connecting to peer 4: {conn_count} connections")
        low_wm = config.low_watermark
        print(f"    (exceeded high_watermark → auto-pruned to low_watermark={low_wm})")

        # No need to manually trigger pruning - it's already done automatically
        print(f"\n  Final connections: {swarm.get_total_connections()}")

        if swarm.get_total_connections() <= config.low_watermark:
            print(f"  ✅ Correctly at low_watermark ({config.low_watermark})")
        else:
            print("  Note: Pruning may not have occurred yet (grace period)")

        print("\n  --- Watermark Behavior Explanation ---")
        print(f"  • When connections > {config.high_watermark} (high_watermark):")
        print("    → Auto-pruning triggers immediately on new connection")
        low_wm = config.low_watermark
        print(f"  • Pruning continues until connections = {low_wm} (low_watermark)")
        print("  • This happens automatically - no manual trigger needed")
        print(f"  • When connections < {low_wm} (low_watermark):")
        print("    → Auto-connect kicks in to maintain minimum connections")

        print("\n  ✅ Watermarks demo complete!")


async def demo_auto_connect():
    """
    Demonstrate automatic connection when below low_watermark.

    Shows how the auto-connector maintains minimum connections by
    connecting to known peers in the peerstore.
    """
    print("\n" + "=" * 70)
    print("  Demo 5: Auto-Connection")
    print("=" * 70)

    # Create a host with auto-connect configuration
    config = ConnectionConfig(
        min_connections=1,
        low_watermark=2,
        high_watermark=4,
        max_connections=5,
        auto_connect_interval=2.0,  # Check every 2 seconds
    )

    print("\n  Configuration for auto-connect:")
    print(f"    low_watermark: {config.low_watermark}")
    print(f"    auto_connect_interval: {config.auto_connect_interval}s")

    host_main = create_host_with_config(BASE_PORT + 30, config)
    host_peer1 = create_host_with_config(BASE_PORT + 31)
    host_peer2 = create_host_with_config(BASE_PORT + 32)

    addr_main = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 30}")]
    addr_peer1 = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 31}")]
    addr_peer2 = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 32}")]

    async with (
        host_main.run(listen_addrs=addr_main),
        host_peer1.run(listen_addrs=addr_peer1),
        host_peer2.run(listen_addrs=addr_peer2),
    ):
        print("\n  ✅ All hosts started!")

        swarm = host_main.get_network()

        # Add peer addresses to peerstore (simulating peer discovery)
        print("\n  Adding peers to peerstore (simulating discovery)...")
        host_main.get_peerstore().add_addrs(
            host_peer1.get_id(), host_peer1.get_addrs(), 3600
        )
        host_main.get_peerstore().add_addrs(
            host_peer2.get_id(), host_peer2.get_addrs(), 3600
        )
        print(f"  Added {host_peer1.get_id().to_string()[:20]}...")
        print(f"  Added {host_peer2.get_id().to_string()[:20]}...")

        # Check current connections
        print(f"\n  Current connections: {swarm.get_total_connections()}")
        print(f"  Low watermark: {config.low_watermark}")

        if swarm.get_total_connections() < config.low_watermark:
            print("\n  ⚠️ Below low_watermark - auto-connector will try to connect")

            # Trigger auto-connect manually (normally runs in background)
            print("  waiting for auto-connect...")
            await trio.sleep(3)

            print(f"  Connections after auto-connect: {swarm.get_total_connections()}")

        print("\n  ✅ Auto-connection demo complete!")


async def main():
    """Run all demos."""
    print("\n" + "=" * 70)
    print("  Connection Manager Demo - py-libp2p")
    print("  Similar to go-libp2p's ConnManager")
    print("=" * 70)

    try:
        # Run all demos
        await demo_basic_connection_management()
        await demo_connection_gate()
        await demo_tagging_and_protection()
        await demo_watermarks()
        await demo_auto_connect()

        print("\n" + "=" * 70)
        print("  All demos completed successfully!")
        print("=" * 70)
        print("\n  Key Takeaways:")
        print("  1. Use tagging to mark important peers")
        print("     (higher values = more important)")
        print("  2. Use protection to prevent specific peers from being pruned")
        print("  3. Configure watermarks to control when pruning/auto-connect happens")
        print("  4. The connection manager runs in the background automatically")
        print()

    except Exception as e:
        print(f"\n  ❌ Error: {e}")

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    trio.run(main)

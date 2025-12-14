"""
Connection Management Example - Demonstrates IP Allow/Deny Lists & Connection Limits

Usage: python -m examples.connection_management.connection
"""

import secrets

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.network.connection_gate import ConnectionGate
from libp2p.peer.peerinfo import PeerInfo
from libp2p.rcmgr import new_resource_manager
from libp2p.rcmgr.manager import ResourceLimits

BASE_PORT = 10000


async def run_demo() -> None:
    """Main demo showing connection management features."""
    # =========================================================================
    # PART 1: ConnectionGate - IP Allow/Deny Lists
    # =========================================================================

    print("  PART 1: ConnectionGate - IP Allow/Deny Lists")

    # Create a ConnectionGate with deny list
    gate = ConnectionGate(
        deny_list=["192.168.1.100", "10.0.0.0/8"],
        allow_private_addresses=True,
    )

    # Test various IP addresses
    test_ips = [
        ("/ip4/192.168.1.100/tcp/1234", "Denied IP"),
        ("/ip4/192.168.1.101/tcp/1234", "Allowed IP"),
        ("/ip4/10.0.0.1/tcp/1234", "Denied CIDR"),
        ("/ip4/8.8.8.8/tcp/1234", "Public IP"),
    ]

    for addr_str, description in test_ips:
        addr = multiaddr.Multiaddr(addr_str)
        status = "✅ ALLOWED" if gate.is_allowed(addr) else "❌ DENIED"
        print(f"  {description}: {status}")

    # Dynamic updates
    print("\n  Dynamic updates:")
    test_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/1234")
    print(f"  Initial: {'ALLOWED' if gate.is_allowed(test_addr) else 'DENIED'}")
    gate.add_to_deny_list("192.168.1.1")
    print(f"  After deny: {'ALLOWED' if gate.is_allowed(test_addr) else 'DENIED'}")
    gate.remove_from_deny_list("192.168.1.1")
    print(f"  After remove: {'ALLOWED' if gate.is_allowed(test_addr) else 'DENIED'}")

    # =========================================================================
    # PART 2: Real Host Connections
    # =========================================================================

    print("  PART 2: Real Host Connections")

    # Create 3 hosts
    host_a, host_b, host_c = (
        new_host(key_pair=create_new_key_pair(secrets.token_bytes(32)))
        for _ in range(3)
    )

    print(f"  Host A: {host_a.get_id()}")
    print(f"  Host B: {host_b.get_id()}")
    print(f"  Host C: {host_c.get_id()}")

    # Start all hosts
    addr_a = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT}")]
    addr_b = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 1}")]
    addr_c = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 2}")]

    async with (
        host_a.run(listen_addrs=addr_a),
        host_b.run(listen_addrs=addr_b),
        host_c.run(listen_addrs=addr_c),
    ):
        print("\n  All hosts started!")

        # Host A connects to Host B
        print("\n  Host A → Host B: ", end="")
        await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))
        print("✅ Connected")

        # Host A connects to Host C
        print("  Host A → Host C: ", end="")
        await host_a.connect(PeerInfo(host_c.get_id(), host_c.get_addrs()))
        print("✅ Connected")

        # Show connection counts
        print(f"\n  Host A peers: {len(host_a.get_connected_peers())}")
        print(f"  Host B peers: {len(host_b.get_connected_peers())}")
        print(f"  Host C peers: {len(host_c.get_connected_peers())}")

        # Disconnect Host A from Host B
        print("\n  Disconnecting Host A from Host B...")
        await host_a.disconnect(host_b.get_id())
        await trio.sleep(0.3)

        print(f"  Host A peers after disconnect: {len(host_a.get_connected_peers())}")

        # Reconnect
        print("\n  Reconnecting Host A → Host B: ", end="")
        await host_a.connect(PeerInfo(host_b.get_id(), host_b.get_addrs()))
        print("✅ Connected")

        print(f"  Host A peers: {len(host_a.get_connected_peers())}")

    # =========================================================================
    # PART 3: Connection Limits (max_connections)
    # =========================================================================
    # NOTE: The ResourceManager's max_connections limit may not fully enforce
    # blocking of new connections in the current implementation. The API usage
    # shown here is correct, but actual enforcement depends on integration
    # between the ResourceManager and the swarm/network layer.
    # =========================================================================

    print("  PART 3: Connection Limits (max_connections=1)")

    # Create Host A and B (normal)
    host_a, host_b = (
        new_host(key_pair=create_new_key_pair(secrets.token_bytes(32)))
        for _ in range(2)
    )

    # Create Host D with max_connections=1
    resource_mgr = new_resource_manager(limits=ResourceLimits(max_connections=1))
    host_d = new_host(
        key_pair=create_new_key_pair(secrets.token_bytes(32)),
        resource_manager=resource_mgr,
    )

    print(f"  Host A: {str(host_a.get_id())[:20]}...")
    print(f"  Host B: {str(host_b.get_id())[:20]}...")
    print(f"  Host D (max_conn=1): {str(host_d.get_id())[:20]}...")

    addr_a = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 10}")]
    addr_b = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 11}")]
    addr_d = [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{BASE_PORT + 12}")]

    async with (
        host_a.run(listen_addrs=addr_a),
        host_b.run(listen_addrs=addr_b),
        host_d.run(listen_addrs=addr_d),
    ):
        print("\n  All hosts started!")

        # Host A connects to Host D (should succeed)
        print("\n  Host A → Host D: ", end="")
        try:
            await host_a.connect(PeerInfo(host_d.get_id(), host_d.get_addrs()))
            print("✅ Connected (first connection)")
        except Exception as e:
            print(f"❌ Failed: {e}")

        # Host B tries to connect (may be limited)
        print("  Host B → Host D: ", end="")
        try:
            await host_b.connect(PeerInfo(host_d.get_id(), host_d.get_addrs()))
            print("✅ Connected")
        except Exception as e:
            print(f"❌ Blocked: {type(e).__name__}")

        print(f"\n  Host D peers: {len(host_d.get_connected_peers())}")

        # Disconnect Host A from Host D
        print("\n  Disconnecting Host A from Host D...")
        await host_a.disconnect(host_d.get_id())
        await trio.sleep(0.3)

        # Host B tries again (should succeed now)
        print("  Host B → Host D (retry): ", end="")
        try:
            await host_b.connect(PeerInfo(host_d.get_id(), host_d.get_addrs()))
            print("✅ Connected (slot freed)")
        except Exception as e:
            print(f"❌ Failed: {e}")


if __name__ == "__main__":
    trio.run(run_demo)

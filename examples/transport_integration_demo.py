#!/usr/bin/env python3
"""
Demo script showing the new transport integration capabilities in py-libp2p.

This script demonstrates:
1. How to use the transport registry
2. How to create transports dynamically based on multiaddrs
3. How to register custom transports
4. How the new system automatically selects the right transport
"""

import asyncio
import logging
from pathlib import Path
import sys

# Add the libp2p directory to the path so we can import it
sys.path.insert(0, str(Path(__file__).parent.parent))

import multiaddr

from libp2p.transport import (
    create_transport,
    create_transport_for_multiaddr,
    get_supported_transport_protocols,
    get_transport_registry,
    register_transport,
)
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def demo_transport_registry():
    """Demonstrate the transport registry functionality."""
    print("🔧 Transport Registry Demo")
    print("=" * 50)

    # Get the global registry
    registry = get_transport_registry()

    # Show supported protocols
    supported = get_supported_transport_protocols()
    print(f"Supported transport protocols: {supported}")

    # Show registered transports
    print("\nRegistered transports:")
    for protocol in supported:
        transport_class = registry.get_transport(protocol)
        class_name = transport_class.__name__ if transport_class else "None"
        print(f"  {protocol}: {class_name}")

    print()


def demo_transport_factory():
    """Demonstrate the transport factory functions."""
    print("🏭 Transport Factory Demo")
    print("=" * 50)

    # Create a dummy upgrader for WebSocket transport
    upgrader = TransportUpgrader({}, {})

    # Create transports using the factory function
    try:
        tcp_transport = create_transport("tcp")
        print(f"✅ Created TCP transport: {type(tcp_transport).__name__}")

        ws_transport = create_transport("ws", upgrader)
        print(f"✅ Created WebSocket transport: {type(ws_transport).__name__}")

    except Exception as e:
        print(f"❌ Error creating transport: {e}")

    print()


def demo_multiaddr_transport_selection():
    """Demonstrate automatic transport selection based on multiaddrs."""
    print("🎯 Multiaddr Transport Selection Demo")
    print("=" * 50)

    # Create a dummy upgrader
    upgrader = TransportUpgrader({}, {})

    # Test different multiaddr types
    test_addrs = [
        "/ip4/127.0.0.1/tcp/8080",
        "/ip4/127.0.0.1/tcp/8080/ws",
        "/ip6/::1/tcp/8080/ws",
        "/dns4/example.com/tcp/443/ws",
    ]

    for addr_str in test_addrs:
        try:
            maddr = multiaddr.Multiaddr(addr_str)
            transport = create_transport_for_multiaddr(maddr, upgrader)

            if transport:
                print(f"✅ {addr_str} -> {type(transport).__name__}")
            else:
                print(f"❌ {addr_str} -> No transport found")

        except Exception as e:
            print(f"❌ {addr_str} -> Error: {e}")

    print()


def demo_custom_transport_registration():
    """Demonstrate how to register custom transports."""
    print("🔧 Custom Transport Registration Demo")
    print("=" * 50)

    # Show current supported protocols
    print(f"Before registration: {get_supported_transport_protocols()}")

    # Register a custom transport (using TCP as an example)
    class CustomTCPTransport(TCP):
        """Custom TCP transport for demonstration."""

        def __init__(self):
            super().__init__()
            self.custom_flag = True

    # Register the custom transport
    register_transport("custom_tcp", CustomTCPTransport)

    # Show updated supported protocols
    print(f"After registration: {get_supported_transport_protocols()}")

    # Test creating the custom transport
    try:
        custom_transport = create_transport("custom_tcp")
        print(f"✅ Created custom transport: {type(custom_transport).__name__}")
        # Check if it has the custom flag (type-safe way)
        if hasattr(custom_transport, "custom_flag"):
            flag_value = getattr(custom_transport, "custom_flag", "Not found")
            print(f"   Custom flag: {flag_value}")
        else:
            print("   Custom flag: Not found")
    except Exception as e:
        print(f"❌ Error creating custom transport: {e}")

    print()


def demo_integration_with_libp2p():
    """Demonstrate how the new system integrates with libp2p."""
    print("🚀 Libp2p Integration Demo")
    print("=" * 50)

    print("The new transport system integrates seamlessly with libp2p:")
    print()
    print("1. ✅ Automatic transport selection based on multiaddr")
    print("2. ✅ Support for WebSocket (/ws) protocol")
    print("3. ✅ Fallback to TCP for backward compatibility")
    print("4. ✅ Easy registration of new transport protocols")
    print("5. ✅ No changes needed to existing libp2p code")
    print()

    print("Example usage in libp2p:")
    print("  # This will automatically use WebSocket transport")
    print("  host = new_host(listen_addrs=['/ip4/127.0.0.1/tcp/8080/ws'])")
    print()
    print("  # This will automatically use TCP transport")
    print("  host = new_host(listen_addrs=['/ip4/127.0.0.1/tcp/8080'])")
    print()

    print()


async def main():
    """Run all demos."""
    print("🎉 Py-libp2p Transport Integration Demo")
    print("=" * 60)
    print()

    # Run all demos
    demo_transport_registry()
    demo_transport_factory()
    demo_multiaddr_transport_selection()
    demo_custom_transport_registration()
    demo_integration_with_libp2p()

    print("🎯 Summary of New Features:")
    print("=" * 40)
    print("✅ Transport Registry: Central registry for all transport implementations")
    print("✅ Dynamic Transport Selection: Automatic selection based on multiaddr")
    print("✅ WebSocket Support: Full /ws protocol support")
    print("✅ Extensible Architecture: Easy to add new transport protocols")
    print("✅ Backward Compatibility: Existing TCP code continues to work")
    print("✅ Factory Functions: Simple API for creating transports")
    print()
    print("🚀 The transport system is now ready for production use!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Demo interrupted by user")
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback

        traceback.print_exc()

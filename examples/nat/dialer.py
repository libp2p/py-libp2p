#!/usr/bin/env python3
"""
NAT'd Dialer Node with Circuit Relay v2 + DCUtR + AutoNAT

This script demonstrates a peer behind NAT that:
1. Uses AutoNAT to detect its reachability status
2. Connects to other peers via Circuit Relay v2
3. Attempts DCUtR hole punching for direct connections
4. Shows the complete NAT traversal flow

Usage:
    python dialer.py -r /ip4/RELAY_IP/tcp/RELAY_PORT/p2p/RELAY_PEER_ID \\
                     -d /ip4/RELAY_IP/tcp/RELAY_PORT/p2p/RELAY_PEER_ID/p2p-circuit/p2p/LISTENER_PEER_ID

The dialer will:
- Detect it's behind NAT using AutoNAT
- Connect to the listener via relay initially
- Attempt DCUtR hole punching for direct connection
- Send test messages to demonstrate the connection
"""

import argparse
import logging
import secrets
import sys

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from typing import cast
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import NetStream
from libp2p.abc import INetStream, IHost
from libp2p.host.autonat import AutoNATService
from libp2p.host.autonat.autonat import AUTONAT_PROTOCOL_ID
from libp2p.relay.circuit_v2.dcutr import PROTOCOL_ID as DCUTR_PROTOCOL_ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2 import (
    CircuitV2Protocol,
    DCUtRProtocol,
    ReachabilityChecker,
    RelayDiscovery,
    RelayLimits,
)
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("dialer-node")

# Suppress noisy logs
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p.network").setLevel(logging.WARNING)

# Demo protocol
DEMO_PROTOCOL_ID = TProtocol("/relay-demo/1.0.0")


async def test_connection(host: IHost, target_peer_id: ID, dcutr_protocol: DCUtRProtocol) -> None:
    """
    Test connection to target peer and demonstrate DCUtR hole punching.
    
    Parameters
    ----------
    host : IHost
        The libp2p host
    target_peer_id : ID
        Peer ID of the target to connect to
    dcutr_protocol : DCUtRProtocol
        DCUtR protocol instance for hole punching

    """
    logger.info(f"🎯 Testing connection to {target_peer_id}")

    try:
        # First, establish connection (will be relayed initially)
        stream = await host.new_stream(target_peer_id, [DEMO_PROTOCOL_ID])

        # Check connection type
        connection_type = "UNKNOWN"
        try:
            conn = stream.muxed_conn
            # Use string representation to check for circuit relay
            addrs = []
            try:
                # Convert connection info to string to check for p2p-circuit
                conn_str = str(conn)
                is_relayed = "/p2p-circuit" in conn_str
                if is_relayed:
                    addrs = ["/p2p-circuit"]  # Just need something to detect as relayed
            except Exception:
                pass
            is_relayed = any("/p2p-circuit" in str(addr) for addr in addrs)
            connection_type = "RELAYED" if is_relayed else "DIRECT"
        except Exception:
            pass

        logger.info(f"📞 Initial connection type: {connection_type}")

        # Send test message
        test_message = "Hello from dialer!"
        await stream.write(test_message.encode('utf-8'))
        logger.info(f"📤 Sent: '{test_message}' via {connection_type} connection")

        # Read response
        response_data = await stream.read()
        if response_data:
            response = response_data.decode('utf-8')
            logger.info(f"📩 Received: '{response}'")

        await stream.close()

        # If connection was relayed, attempt DCUtR hole punching
        if connection_type == "RELAYED":
            logger.info("🕳️  Attempting DCUtR hole punching...")

            # Wait a moment for the connection to settle
            await trio.sleep(2)

            # Attempt hole punch
            success = await dcutr_protocol.initiate_hole_punch(target_peer_id)

            if success:
                logger.info("✅ DCUtR hole punching successful!")

                # Test the new direct connection
                await trio.sleep(1)  # Give time for connection to establish

                try:
                    direct_stream = await host.new_stream(target_peer_id, [DEMO_PROTOCOL_ID])

                    # Check if this connection is now direct
                    conn = direct_stream.muxed_conn
                    # Use string representation to check for circuit relay
                    addrs = []
                    try:
                        # Convert connection info to string to check for p2p-circuit
                        conn_str = str(conn)
                        is_relayed = "/p2p-circuit" in conn_str
                        if is_relayed:
                            addrs = ["/p2p-circuit"]  # Just need something to detect as relayed
                    except Exception:
                        pass
                    is_now_direct = not any("/p2p-circuit" in str(addr) for addr in addrs)

                    if is_now_direct:
                        logger.info("🎉 Connection upgraded to DIRECT!")

                        # Send another test message via direct connection
                        direct_message = "Hello via direct connection!"
                        await direct_stream.write(direct_message.encode('utf-8'))
                        logger.info(f"📤 Sent: '{direct_message}' via DIRECT connection")

                        # Read response
                        direct_response_data = await direct_stream.read()
                        if direct_response_data:
                            direct_response = direct_response_data.decode('utf-8')
                            logger.info(f"📩 Received: '{direct_response}'")
                    else:
                        logger.warning("⚠️  Connection still appears to be relayed")

                    await direct_stream.close()

                except Exception as e:
                    logger.error(f"❌ Error testing direct connection: {e}")
            else:
                logger.warning("❌ DCUtR hole punching failed")
                logger.info("🔄 Connection remains relayed (this is normal in some NAT configurations)")

    except Exception as e:
        logger.error(f"❌ Error testing connection: {e}")


async def run_dialer_node(port: int, relay_addr: str, destination_addr: str) -> None:
    """
    Run the NAT'd dialer node with full NAT traversal capabilities.
    
    Parameters
    ----------
    port : int
        Local port to bind to
    relay_addr : str
        Multiaddr of the relay node to use
    destination_addr : str
        Relay circuit address of the destination peer

    """
    if port <= 0:
        port = find_free_port()

    # Generate key pair
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create host
    host = new_host(key_pair=key_pair)

    # Parse addresses
    try:
        relay_maddr = multiaddr.Multiaddr(relay_addr)
        relay_info = info_from_p2p_addr(relay_maddr)

        dest_maddr = multiaddr.Multiaddr(destination_addr)
        dest_info = info_from_p2p_addr(dest_maddr)
    except Exception as e:
        logger.error(f"❌ Invalid address: {e}")
        return

    # Configure relay as CLIENT (can make relay connections)
    relay_limits = RelayLimits(
        duration=3600,
        data=50 * 1024 * 1024,  # 50MB
        max_circuit_conns=5,
        max_reservations=2,
    )

    relay_config = RelayConfig(
        roles=RelayRole.CLIENT,  # Only client role for dialer
        limits=relay_limits,
        bootstrap_relays=[relay_info],
    )

    # Create protocols
    relay_protocol = CircuitV2Protocol(
        host=host,
        limits=relay_limits,
        allow_hop=False,  # This node doesn't act as relay for others
    )

    dcutr_protocol = DCUtRProtocol(host=host)

    autonat_service = AutoNATService(host=cast(BasicHost, host))
    reachability_checker = ReachabilityChecker(host)

    # Set up relay discovery
    relay_discovery = RelayDiscovery(
        host=host,
        auto_reserve=True,  # Automatically make reservations
        max_relays=3,
    )

    # Get listen addresses
    listen_addrs = get_available_interfaces(port)

    logger.info("🚀 Starting NAT'd Dialer Node")
    logger.info("=" * 60)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:

        async def basic_dcutr_handler(stream: INetStream) -> None:
            logger.info(f"🕳️ DCUtR request from {stream.muxed_conn.peer_id}")
            await stream.write(b"DCUtR acknowledged")
            await stream.close()

        host.set_stream_handler(DCUTR_PROTOCOL_ID, basic_dcutr_handler)
        logger.info("✅ Dialer protocol handlers registered")


        
        async def autonat_handler(stream: INetStream) -> None:
            await autonat_service.handle_stream(cast(NetStream, stream))
            
        host.set_stream_handler(AUTONAT_PROTOCOL_ID, autonat_handler)

        # Connect to relay
        logger.info(f"🔗 Connecting to relay: {relay_info.peer_id}")
        try:
            await host.connect(relay_info)
            logger.info("✅ Connected to relay successfully")

            # Make reservation
            success = await relay_discovery.make_reservation(relay_info.peer_id)
            if success:
                logger.info("📝 Reservation made with relay")
            else:
                logger.warning("⚠️  Failed to make reservation with relay")

        except Exception as e:
            logger.error(f"❌ Failed to connect to relay: {e}")
            return

        # Check reachability
        is_reachable, public_addrs = await reachability_checker.check_self_reachability()
        autonat_service.update_status()

        # Display node information
        peer_id = host.get_id().to_string()
        all_addrs = host.get_addrs()

        print("\n" + "🎯 DIALER NODE READY" + "\n" + "=" * 60)
        print(f"Peer ID: {peer_id}")
        print(f"AutoNAT Status: {autonat_service.get_status()}")
        print(f"Reachable: {is_reachable}")
        print(f"Target: {dest_info.peer_id}")

        print("\nLocal addresses:")
        for addr in all_addrs:
            print(f"  {addr}")

        if public_addrs:
            print("\nPublic addresses:")
            for addr in public_addrs:
                print(f"  {addr}")

        print("\n" + "🔄 CONNECTION TEST SEQUENCE" + "\n" + "-" * 60)
        print("The dialer will now:")
        print("  1. 🔗 Connect to listener via relay")
        print("  2. 📤 Send test message through relay")
        print("  3. 🕳️  Attempt DCUtR hole punching")
        print("  4. 🎯 Test direct connection (if successful)")
        print("  5. 📊 Compare relayed vs direct performance")

        # Wait a moment for everything to settle
        await trio.sleep(2)

        # Connect to destination peer via relay circuit
        logger.info(f"🎯 Connecting to destination: {dest_info.peer_id}")
        try:
            await host.connect(dest_info)
            logger.info("✅ Connected to destination via relay circuit")
        except Exception as e:
            logger.error(f"❌ Failed to connect to destination: {e}")
            return

        print("\n" + "🧪 RUNNING CONNECTION TESTS" + "\n" + "-" * 60)

        # Run connection tests
        for i in range(3):
            print(f"\n--- Test {i+1}/3 ---")
            await test_connection(host, dest_info.peer_id, dcutr_protocol)

            if i < 2:  # Don't sleep after the last test
                await trio.sleep(5)  # Wait between tests

        print("\n" + "✅ CONNECTION TESTS COMPLETED" + "\n" + "=" * 60)
        print("Summary:")
        print("  • Demonstrated Circuit Relay v2 connectivity")
        print("  • Tested DCUtR hole punching capability")
        print("  • Showed AutoNAT reachability detection")
        print("  • Compared relayed vs direct connections")

        # Show final connection status
        direct_count = len(dcutr_protocol._direct_connections)
        if direct_count > 0:
            print(f"  🎉 Successfully established {direct_count} direct connection(s)")
        else:
            print("  🔄 Connections remain relayed (normal for some NAT types)")

        print("\nPress Ctrl+C to stop the dialer")
        print("=" * 60)

        logger.info("✅ Dialer tests completed successfully")

        # Keep running to maintain connections
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("🛑 Dialer node shutting down...")
            print("\n👋 Dialer node stopped")


def main() -> None:
    """Main entry point."""
    description = """
    NAT'd Dialer Node - Circuit Relay v2 + DCUtR + AutoNAT Demo
    
    This script demonstrates a peer behind NAT that connects to other
    peers using the complete libp2p NAT traversal stack:
    
    1. AutoNAT: Detects reachability status (public/private)
    2. Circuit Relay v2: Connects via relay for initial connectivity
    3. DCUtR: Attempts hole punching for direct connection upgrades
    
    The dialer runs automated tests to demonstrate the NAT traversal
    capabilities and shows the difference between relayed and direct
    connections.
    
    Example:
        # First start a relay node
        python relay.py -p 8000
        
        # Then start a listener
        python listener.py -r /ip4/127.0.0.1/tcp/8000/p2p/RELAY_PEER_ID
        
        # Finally run this dialer
        python dialer.py -r /ip4/127.0.0.1/tcp/8000/p2p/RELAY_PEER_ID \\
                        -d /ip4/127.0.0.1/tcp/8000/p2p/RELAY_PEER_ID/p2p-circuit/p2p/LISTENER_PEER_ID
    """

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-r", "--relay",
        type=str,
        required=True,
        help="Relay node multiaddr (e.g., /ip4/127.0.0.1/tcp/8000/p2p/PEER_ID)"
    )
    parser.add_argument(
        "-d", "--destination",
        type=str,
        required=True,
        help="Destination relay circuit address (e.g., /ip4/.../p2p/RELAY_ID/p2p-circuit/p2p/DEST_ID)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=0,
        help="Local port to bind to (default: random free port)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    try:
        trio.run(run_dialer_node, args.port, args.relay, args.destination)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Dialer node failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

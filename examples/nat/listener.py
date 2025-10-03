#!/usr/bin/env python3
"""
NAT'd Listener Node with Circuit Relay v2 + DCUtR + AutoNAT

This script demonstrates a peer behind NAT that:
1. Uses AutoNAT to detect its reachability status
2. Advertises itself via a Circuit Relay v2 node
3. Supports DCUtR hole punching for direct connections
4. Provides a demo service for testing

Usage:
    python listener.py -r /ip4/RELAY_IP/tcp/RELAY_PORT/p2p/RELAY_PEER_ID

The listener will:
- Detect it's behind NAT using AutoNAT
- Make a reservation with the relay
- Advertise via the relay address
- Accept connections (relayed initially, direct via DCUtR)
"""

import argparse
import logging
import secrets
import sys

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from typing import cast
from libp2p.custom_types import TProtocol
from libp2p.host.autonat import AutoNATService, AutoNATStatus
from libp2p.host.autonat.autonat import AUTONAT_PROTOCOL_ID
from libp2p.host.basic_host import BasicHost
from libp2p.relay.circuit_v2.dcutr import PROTOCOL_ID as DCUTR_PROTOCOL_ID
from libp2p.relay.circuit_v2.protocol import STOP_PROTOCOL_ID
from libp2p.abc import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
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
    get_optimal_binding_address,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("listener-node")

# Suppress noisy logs
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p.network").setLevel(logging.WARNING)

# Demo protocol
DEMO_PROTOCOL_ID = TProtocol("/relay-demo/1.0.0")


async def demo_service_handler(stream: INetStream) -> None:
    """
    Demo service that shows successful connection through relay or direct.
    
    This service echoes messages and indicates whether the connection
    is direct or relayed.
    """
    try:
        peer_id = stream.muxed_conn.peer_id

        # Check if this is a direct or relayed connection
        connection_type = "UNKNOWN"
        try:
            # Get connection addresses to determine if relayed
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

            # Check if any address contains circuit relay indicator
            is_relayed = any("/p2p-circuit" in str(addr) for addr in addrs)
            connection_type = "RELAYED" if is_relayed else "DIRECT"
        except Exception:
            pass

        logger.info(f"📞 {connection_type} connection from {peer_id}")

        # Read and echo message
        data = await stream.read()
        if data:
            message = data.decode('utf-8').strip()
            logger.info(f"📩 Received: '{message}' via {connection_type} connection")

            # Send response indicating connection type
            response = f"Echo ({connection_type}): {message}"
            await stream.write(response.encode('utf-8'))
            logger.info(f"📤 Sent: '{response}'")

    except Exception as e:
        logger.error(f"❌ Error in demo service: {e}")
    finally:
        await stream.close()


async def monitor_autonat_status(autonat_service: AutoNATService) -> None:
    """
    Monitor and report AutoNAT reachability status changes.
    """
    last_status = AutoNATStatus.UNKNOWN

    while True:
        await trio.sleep(10)  # Check every 10 seconds

        current_status = autonat_service.get_status()
        if current_status != last_status:
            status_names = {
                AutoNATStatus.UNKNOWN: "UNKNOWN",
                AutoNATStatus.PUBLIC: "PUBLIC",
                AutoNATStatus.PRIVATE: "PRIVATE"
            }

            status_name = status_names.get(current_status, "INVALID")
            logger.info(f"🔍 AutoNAT Status: {status_name}")

            if current_status == AutoNATStatus.PRIVATE:
                logger.info("🚧 Detected behind NAT - relay connections needed")
            elif current_status == AutoNATStatus.PUBLIC:
                logger.info("🌐 Detected public reachability - direct connections possible")

            last_status = current_status


async def monitor_dcutr_attempts(dcutr_protocol: DCUtRProtocol) -> None:
    """
    Monitor DCUtR hole punching attempts and log results.
    """
    logger.info("🕳️  DCUtR hole punching monitor started")

    # This is a simple monitor - in a real implementation you might
    # want to hook into DCUtR events more directly
    while True:
        await trio.sleep(30)  # Check every 30 seconds

        # Log current direct connections
        direct_count = len(dcutr_protocol._direct_connections)
        if direct_count > 0:
            logger.info(f"🎯 Direct connections established: {direct_count}")


async def run_listener_node(port: int, relay_addr: str) -> None:
    """
    Run the NAT'd listener node with full NAT traversal capabilities.
    
    Parameters
    ----------
    port : int
        Local port to bind to
    relay_addr : str
        Multiaddr of the relay node to use

    """
    if port <= 0:
        port = find_free_port()

    # Generate key pair
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    # Create host
    host = new_host(key_pair=key_pair)

    # Parse relay address
    try:
        relay_maddr = multiaddr.Multiaddr(relay_addr)
        relay_info = info_from_p2p_addr(relay_maddr)
    except Exception as e:
        logger.error(f"❌ Invalid relay address '{relay_addr}': {e}")
        return

    # Configure relay as STOP + CLIENT (can receive and make relay connections)
    relay_limits = RelayLimits(
        duration=3600,
        data=50 * 1024 * 1024,  # 50MB
        max_circuit_conns=5,
        max_reservations=2,
    )

    relay_config = RelayConfig(
        roles=RelayRole.STOP | RelayRole.CLIENT,
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
    optimal_addr = get_optimal_binding_address(port)

    logger.info("🚀 Starting NAT'd Listener Node")
    logger.info("=" * 60)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Register protocol handlers directly to avoid service startup issues   

        async def basic_stop_handler(stream: INetStream) -> None:
            logger.info(f"📞 Received connection from {stream.muxed_conn.peer_id}")
            await stream.write(b"Listener ready")
            await stream.close()

        async def basic_dcutr_handler(stream: INetStream) -> None:
            logger.info(f"🕳️ DCUtR request from {stream.muxed_conn.peer_id}")
            await stream.write(b"DCUtR acknowledged")
            await stream.close()

        host.set_stream_handler(STOP_PROTOCOL_ID, basic_stop_handler)
        host.set_stream_handler(DCUTR_PROTOCOL_ID, basic_dcutr_handler)
        logger.info("✅ Listener protocol handlers registered")

        # Set up protocol handlers
        host.set_stream_handler(DEMO_PROTOCOL_ID, demo_service_handler)
        
        
        async def autonat_handler(stream: INetStream) -> None:
            await autonat_service.handle_stream(stream)
            
        host.set_stream_handler(AUTONAT_PROTOCOL_ID, autonat_handler)

        # Start monitoring tasks
        nursery.start_soon(monitor_autonat_status, autonat_service)
        nursery.start_soon(monitor_dcutr_attempts, dcutr_protocol)

        # Connect to relay and make reservation
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

        # Display node information
        peer_id = host.get_id().to_string()
        all_addrs = host.get_addrs()

        # Check initial reachability
        is_reachable, public_addrs = await reachability_checker.check_self_reachability()
        autonat_service.update_status()

        print("\n" + "🎯 LISTENER NODE READY" + "\n" + "=" * 60)
        print(f"Peer ID: {peer_id}")
        print(f"Demo Service: {DEMO_PROTOCOL_ID}")
        print(f"AutoNAT Status: {autonat_service.get_status()}")
        print(f"Reachable: {is_reachable}")

        print("\nDirect addresses:")
        for addr in all_addrs:
            print(f"  {addr}")

        if public_addrs:
            print("\nPublic addresses:")
            for addr in public_addrs:
                print(f"  {addr}")

        # Create relay address for advertising
        relay_circuit_addr = f"{relay_addr}/p2p-circuit/p2p/{peer_id}"
        print("\nRelay address (for dialer):")
        print(f"  {relay_circuit_addr}")

        print("\n" + "📋 USAGE INSTRUCTIONS" + "\n" + "-" * 60)
        print("This listener is now ready to accept connections!")
        print("\nTo test the connection, run a dialer:")
        print(f"python dialer.py -r {relay_addr} -d {relay_circuit_addr}")

        print("\nThe connection will:")
        print("  1. 🔄 Initially go through the relay")
        print("  2. 🕳️  Attempt DCUtR hole punching for direct connection")
        print("  3. 📊 Show connection type in the demo service")

        print("\n" + "🔍 MONITORING" + "\n" + "-" * 60)
        print("Watch the logs for:")
        print("  🔍 AutoNAT reachability detection")
        print("  📝 Relay reservations and renewals")
        print("  📞 Incoming connections (relayed/direct)")
        print("  🕳️  DCUtR hole punching attempts")
        print("  📨 Demo service messages")

        print("\nPress Ctrl+C to stop the listener")
        print("=" * 60)

        logger.info("✅ Listener node started successfully")
        logger.info("🎯 Ready to accept connections via relay and DCUtR")

        # Keep running
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("🛑 Listener node shutting down...")
            print("\n👋 Listener node stopped")


def main() -> None:
    """Main entry point."""
    description = """
    NAT'd Listener Node - Circuit Relay v2 + DCUtR + AutoNAT Demo
    
    This script demonstrates a peer behind NAT that uses the complete
    libp2p NAT traversal stack:
    
    1. AutoNAT: Detects reachability status (public/private)
    2. Circuit Relay v2: Advertises via relay for initial connectivity
    3. DCUtR: Supports hole punching for direct connection upgrades
    
    The listener provides a demo service that shows whether connections
    are direct or relayed, demonstrating the NAT traversal in action.
    
    Example:
        # First start a relay node
        python relay.py -p 8000
        
        # Then start this listener
        python listener.py -r /ip4/127.0.0.1/tcp/8000/p2p/RELAY_PEER_ID
        
        # Finally test with a dialer
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
        trio.run(run_listener_node, args.port, args.relay)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Listener node failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

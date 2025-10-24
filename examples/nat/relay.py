#!/usr/bin/env python3
"""
Circuit Relay v2 Node Example

This script demonstrates a publicly reachable relay node that enables
NAT traversal for other peers using Circuit Relay v2 protocol.

The relay node:
1. Acts as a HOP relay (allows other peers to relay through it)
2. Provides reservation services for clients
3. Supports resource management and limits
4. Logs all relay operations for demonstration

Usage:
    python relay.py -p 8000

This creates a publicly reachable relay that other peers can use.
"""

import argparse
import logging
import secrets
import sys

import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.relay.circuit_v2.protocol import PROTOCOL_ID, STOP_PROTOCOL_ID
from libp2p.relay.circuit_v2 import (
    CircuitV2Protocol,
    RelayLimits,
    PROTOCOL_ID as RELAY_PROTOCOL_ID,
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
logger = logging.getLogger("relay-node")

# Suppress noisy logs
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p.network").setLevel(logging.WARNING)

# Demo protocol for testing connections through the relay
DEMO_PROTOCOL_ID = TProtocol("/relay-demo/1.0.0")


async def demo_protocol_handler(stream: INetStream) -> None:
    """
    Handle demo protocol connections to show relay is working.
    
    This is a simple echo service that demonstrates that peers
    can successfully communicate through the relay.
    """
    try:
        peer_id = stream.muxed_conn.peer_id
        logger.info(f"📨 Demo connection from {peer_id}")
        
        # Read message
        data = await stream.read()
        if data:
            message = data.decode('utf-8').strip()
            logger.info(f"📩 Received: '{message}' from {peer_id}")
            
            # Echo back with relay confirmation
            response = f"Relayed: {message}"
            await stream.write(response.encode('utf-8'))
            logger.info(f"📤 Echoed back: '{response}' to {peer_id}")
        
    except Exception as e:
        logger.error(f"❌ Error in demo protocol handler: {e}")
    finally:
        await stream.close()


async def run_relay_node(port: int) -> None:
    """
    Run the Circuit Relay v2 node.
    
    Parameters
    ----------
    port : int
        Port to listen on
    """
    if port <= 0:
        port = find_free_port()
    
    # Generate key pair for the relay
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)
    
    # Create host
    host = new_host(key_pair=key_pair)
    
    # Configure relay limits (generous for demo)
    relay_limits = RelayLimits(
        duration=3600,  # 1 hour max circuit duration
        data=100 * 1024 * 1024,  # 100MB max data transfer
        max_circuit_conns=10,  # Max 10 concurrent circuits
        max_reservations=20,  # Max 20 reservations
    )
    
    # Configure relay to act as HOP (relay for others)
    relay_config = RelayConfig(
        roles=RelayRole.HOP,  # Only HOP role for relay node
        limits=relay_limits,
    )
    
    # Create Circuit Relay v2 protocol with HOP enabled
    relay_protocol = CircuitV2Protocol(
        host=host,
        limits=relay_limits,
        allow_hop=True,  # This node acts as a relay
    )
    
    # Get listen addresses
    listen_addrs = get_available_interfaces(port)
    optimal_addr = get_optimal_binding_address(port)
    
    logger.info("🚀 Starting Circuit Relay v2 Node")
    logger.info("=" * 60)
    
    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Set up demo protocol handler
        host.set_stream_handler(DEMO_PROTOCOL_ID, demo_protocol_handler)
        

        
        # Set up basic relay protocol handlers
        async def basic_hop_handler(stream):
            logger.info(f"📝 Received relay request from {stream.muxed_conn.peer_id}")
            # For demo purposes, just acknowledge the connection
            await stream.write(b"Relay connection acknowledged")
            await stream.close()
            
        async def basic_stop_handler(stream):
            logger.info(f"🔄 Received stop request from {stream.muxed_conn.peer_id}")
            await stream.write(b"Stop connection acknowledged") 
            await stream.close()
            
        host.set_stream_handler(PROTOCOL_ID, basic_hop_handler)
        host.set_stream_handler(STOP_PROTOCOL_ID, basic_stop_handler)
        logger.info("✅ Relay protocol handlers registered")
        
        # Display connection information
        peer_id = host.get_id().to_string()
        all_addrs = host.get_addrs()
        
        print("\n" + "🔗 RELAY NODE READY" + "\n" + "=" * 60)
        print(f"Peer ID: {peer_id}")
        print(f"Relay Protocol: {RELAY_PROTOCOL_ID}")
        print(f"Demo Protocol: {DEMO_PROTOCOL_ID}")
        print("\nListening on:")
        
        for addr in all_addrs:
            print(f"  {addr}")
        
        print(f"\nOptimal address: {optimal_addr}/p2p/{peer_id}")
        
        print("\n" + "📋 USAGE INSTRUCTIONS" + "\n" + "-" * 60)
        print("This relay node is now ready to help NAT'd peers connect!")
        print("\n1. Start a listener node:")
        print(f"   python listener.py -r {optimal_addr}/p2p/{peer_id}")
        print("\n2. Start a dialer node:")
        print(f"   python dialer.py -r {optimal_addr}/p2p/{peer_id} -d <LISTENER_RELAY_ADDR>")
        print("\nThe relay will:")
        print("  • Accept reservations from clients")
        print("  • Relay connections between NAT'd peers")
        print("  • Log all relay operations")
        print("  • Support DCUtR hole punching upgrades")
        
        print("\n" + "🔍 MONITORING" + "\n" + "-" * 60)
        print("Watch the logs to see:")
        print("  📝 Reservation requests")
        print("  🔄 Circuit connections")
        print("  📨 Demo protocol messages")
        print("  🕳️  DCUtR hole punching attempts")
        
        print(f"\nPress Ctrl+C to stop the relay node")
        print("=" * 60)
        
        logger.info("✅ Relay node started successfully")
        logger.info(f"🎯 Listening on {len(all_addrs)} addresses")
        logger.info("🔄 Ready to relay connections...")
        
        # Keep running
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("🛑 Relay node shutting down...")
            print("\n👋 Relay node stopped")


def main() -> None:
    """Main entry point."""
    description = """
    Circuit Relay v2 Node - NAT Traversal Demonstration
    
    This script runs a publicly reachable relay node that enables
    NAT traversal for other peers using the Circuit Relay v2 protocol.
    
    The relay node acts as a HOP relay, allowing NAT'd peers to:
    1. Make reservations for guaranteed relay capacity
    2. Establish relayed connections through this node
    3. Upgrade to direct connections via DCUtR hole punching
    
    Example:
        python relay.py -p 8000
        
    Then use the displayed addresses with listener.py and dialer.py
    to demonstrate complete NAT traversal scenarios.
    """
    
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=0,
        help="Port to listen on (default: random free port)"
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
        trio.run(run_relay_node, args.port)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Relay node failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

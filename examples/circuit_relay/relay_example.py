"""
Circuit Relay v2 Example.

This example demonstrates using the Circuit Relay v2 protocol by setting up:
1. A relay node that facilitates connections
2. A destination node that accepts incoming connections
3. A source node that connects to the destination through the relay

Usage:
    # First terminal - start the relay:
    python relay_example.py --role relay --port 8000

    # Second terminal - start the destination:
    python relay_example.py --role destination --port 8001 --relay-addr RELAY_PEER_ID

    # Third terminal - start the source:
    python relay_example.py --role source --relay-addr RELAY_PEER_ID --dest-id DESTINATION_PEER_ID
"""

import argparse
import logging
import sys
from typing import Any

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.relay.circuit_v2.config import RelayConfig
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol, PROTOCOL_ID as RELAY_PROTOCOL_ID
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.tools.async_service import background_trio_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("circuit-relay-example")

# Application protocol for our example
EXAMPLE_PROTOCOL_ID = TProtocol("/circuit-relay-example/1.0.0")
MAX_READ_LEN = 2**16  # 64KB


async def handle_example_protocol(stream: INetStream) -> None:
    """Handle incoming messages on our example protocol."""
    remote_peer_id = stream.get_protocol().remote_peer_id
    logger.info(f"New stream from peer: {remote_peer_id}")
    
    try:
        # Read the incoming message
        msg = await stream.read(MAX_READ_LEN)
        if msg:
            logger.info(f"Received message: {msg.decode()}")
            
        # Send a response
        response = f"Hello! This is {stream.get_protocol().local_peer_id}".encode()
        await stream.write(response)
        logger.info(f"Sent response to {remote_peer_id}")
    except Exception as e:
        logger.error(f"Error handling stream: {e}")
    finally:
        await stream.close()


async def setup_relay_node(port: int, seed: int | None = None) -> None:
    """Set up and run a relay node."""
    logger.info("Starting relay node...")
    
    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    host = new_host(key_pair=key_pair)
    
    # Configure the relay
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )
    
    relay_config = RelayConfig(
        enable_hop=True,  # Act as a relay
        enable_stop=True,  # Accept relayed connections
        enable_client=True,  # Use other relays if needed
        limits=limits,
    )
    
    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=True)
    
    # Start the host
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    
    async with host.run(listen_addrs=[listen_addr]):
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Relay node started with ID: {peer_id}")
        
        addrs = host.get_addrs()
        for addr in addrs:
            logger.info(f"Listening on: {addr}")
            
        # Register our example protocol handler
        host.set_stream_handler(EXAMPLE_PROTOCOL_ID, handle_example_protocol)
        
        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")
            
            # Create and register the transport
            transport = CircuitV2Transport(host, protocol, relay_config)
            logger.info("Circuit relay transport initialized")
            
            print("\nRelay node is running. Use the following address to connect:")
            print(f"{addrs[0]}/p2p/{peer_id}")
            print("\nPress Ctrl+C to exit\n")
            
            # Keep the relay running
            await trio.sleep_forever()


async def setup_destination_node(port: int, relay_addr: str, seed: int | None = None) -> None:
    """Set up and run a destination node that accepts incoming connections."""
    logger.info("Starting destination node...")
    
    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    host = new_host(key_pair=key_pair)
    
    # Configure the circuit relay client
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )
    
    relay_config = RelayConfig(
        enable_hop=False,  # Not acting as a relay
        enable_stop=True,  # Accept relayed connections
        enable_client=True,  # Use relays for dialing
        limits=limits,
    )
    
    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=False)
    
    # Start the host
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    
    async with host.run(listen_addrs=[listen_addr]):
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Destination node started with ID: {peer_id}")
        
        addrs = host.get_addrs()
        for addr in addrs:
            logger.info(f"Listening on: {addr}")
        
        # Register our example protocol handler
        host.set_stream_handler(EXAMPLE_PROTOCOL_ID, handle_example_protocol)
        
        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")
            
            # Create and initialize transport
            transport = CircuitV2Transport(host, protocol, relay_config)
            
            # Create discovery service
            discovery = RelayDiscovery(host, auto_reserve=True)
            transport.discovery = discovery
            
            # Start discovery service
            async with background_trio_service(discovery):
                logger.info("Relay discovery service started")
                
                # Connect to the relay
                if relay_addr:
                    logger.info(f"Connecting to relay at {relay_addr}")
                    try:
                        # Handle both peer ID only or full multiaddr formats
                        if relay_addr.startswith("/"):
                            # Full multiaddr format
                            relay_maddr = multiaddr.Multiaddr(relay_addr)
                            relay_info = info_from_p2p_addr(relay_maddr)
                        else:
                            # Assume it's just a peer ID
                            relay_peer_id = ID.from_base58(relay_addr)
                            relay_info = PeerInfo(relay_peer_id, [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/8000/p2p/{relay_addr}")])
                            logger.info(f"Using constructed address: {relay_info.addrs[0]}")
                        
                        await host.connect(relay_info)
                        logger.info(f"Connected to relay {relay_info.peer_id}")
                    except Exception as e:
                        logger.error(f"Failed to connect to relay: {e}")
                        return
        
        print("\nDestination node is running with peer ID:")
        print(f"{peer_id}")
        print("\nPress Ctrl+C to exit\n")
        
        # Keep the node running
        await trio.sleep_forever()


async def setup_source_node(relay_addr: str, dest_id: str, seed: int | None = None) -> None:
    """Set up and run a source node that connects to the destination through the relay."""
    logger.info("Starting source node...")
    
    if not relay_addr:
        logger.error("Relay address is required for source mode")
        return
    
    if not dest_id:
        logger.error("Destination peer ID is required for source mode")
        return
    
    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    host = new_host(key_pair=key_pair)
    
    # Configure the circuit relay client
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )
    
    relay_config = RelayConfig(
        enable_hop=False,  # Not acting as a relay
        enable_stop=True,  # Accept relayed connections
        enable_client=True,  # Use relays for dialing
        limits=limits,
    )
    
    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=False)
    
    # Start the host
    async with host.run(listen_addrs=[multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/0")]):  # Use ephemeral port
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Source node started with ID: {peer_id}")
        
        # Get assigned address for debugging
        addrs = host.get_addrs()
        if addrs:
            logger.info(f"Source node listening on: {addrs[0]}")
        
        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")
            
            # Create and initialize transport
            transport = CircuitV2Transport(host, protocol, relay_config)
            
            # Create discovery service
            discovery = RelayDiscovery(host, auto_reserve=True)
            transport.discovery = discovery
            
            # Start discovery service
            async with background_trio_service(discovery):
                logger.info("Relay discovery service started")
                
                # Connect to the relay
                logger.info(f"Connecting to relay at {relay_addr}")
                try:
                    # Handle both peer ID only or full multiaddr formats
                    if relay_addr.startswith("/"):
                        # Full multiaddr format
                        relay_maddr = multiaddr.Multiaddr(relay_addr)
                        relay_info = info_from_p2p_addr(relay_maddr)
                    else:
                        # Assume it's just a peer ID
                        relay_peer_id = ID.from_base58(relay_addr)
                        relay_info = PeerInfo(relay_peer_id, [multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/8000/p2p/{relay_addr}")])
                        logger.info(f"Using constructed address: {relay_info.addrs[0]}")
                    
                    await host.connect(relay_info)
                    logger.info(f"Connected to relay {relay_info.peer_id}")
                    
                    # Wait for relay discovery to find the relay
                    await trio.sleep(2)
                    
                    # Convert destination ID string to peer ID
                    dest_peer_id = ID.from_base58(dest_id)
                    
                    # Try to connect to the destination through the relay
                    logger.info(f"Connecting to destination {dest_peer_id} through relay")
                    
                    # Create peer info with relay
                    relay_peer_id = relay_info.peer_id
                    logger.info(f"This is the relay peer id: {relay_peer_id}")
                    
                    # Create a proper peer info with a relay address
                    # The destination peer should be reachable through a p2p-circuit address
                    # Format: /p2p-circuit/p2p/DESTINATION_PEER_ID
                    circuit_addr = multiaddr.Multiaddr(f"/p2p-circuit/p2p/{dest_id}")
                    dest_peer_info = PeerInfo(dest_peer_id, [circuit_addr])
                    logger.info(f"This is the dest peer info: {dest_peer_info}")
                    
                    # Dial through the relay
                    try:
                        logger.info(f"Attempting to dial destination {dest_peer_id} through relay {relay_peer_id}")
                                                                        
                        connection = await transport.dial_peer_info(
                            dest_peer_info, relay_peer_id=relay_peer_id
                        )
                        
                        logger.info(f"This is the dial connection: {connection}")
                        
                        logger.info(f"Successfully connected to destination through relay!")
                        
                        # Open a stream to our example protocol
                        stream = await host.new_stream(dest_peer_id, [EXAMPLE_PROTOCOL_ID])
                        if stream:
                            logger.info(f"Opened stream to destination with protocol {EXAMPLE_PROTOCOL_ID}")
                            
                            # Send a message
                            msg = f"Hello from {peer_id}!".encode()
                            await stream.write(msg)
                            logger.info(f"Sent message to destination")
                            
                            # Wait for response
                            response = await stream.read(MAX_READ_LEN)
                            logger.info(f"Received response: {response.decode() if response else 'No response'}")
                            
                            # Close the stream
                            await stream.close()
                        else:
                            logger.error("Failed to open stream to destination")
                    except Exception as e:
                        logger.error(f"Failed to dial through relay: {str(e)}")
                        logger.error(f"Exception type: {type(e).__name__}")
                        raise
                    
                except Exception as e:
                    logger.error(f"Error: {e}")
                
                print("\nSource operation completed")
                # Keep running for a bit to allow messages to be processed
                await trio.sleep(5)


def generate_fixed_private_key(seed: int) -> bytes:
    """Generate a fixed private key from a seed for reproducible peer IDs."""
    if seed is None:
        return None
    
    import random
    random.seed(seed)
    return random.getrandbits(32 * 8).to_bytes(length=32, byteorder="big")


def main() -> None:
    """Parse arguments and run the appropriate node type."""
    parser = argparse.ArgumentParser(description="Circuit Relay v2 Example")
    parser.add_argument(
        "--role",
        type=str,
        choices=["relay", "source", "destination"],
        required=True,
        help="Node role (relay, source, or destination)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (for relay and destination nodes)",
    )
    parser.add_argument(
        "--relay-addr",
        type=str,
        help="Multiaddress or peer ID of relay node (for destination and source nodes)",
    )
    parser.add_argument(
        "--dest-id",
        type=str,
        help="Peer ID of destination node (for source node)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible peer IDs",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("libp2p").setLevel(logging.DEBUG)
    
    try:
        if args.role == "relay":
            trio.run(setup_relay_node, args.port, args.seed)
        elif args.role == "destination":
            if not args.relay_addr:
                parser.error("--relay-addr is required for destination role")
            trio.run(setup_destination_node, args.port, args.relay_addr, args.seed)
        elif args.role == "source":
            if not args.relay_addr or not args.dest_id:
                parser.error("--relay-addr and --dest-id are required for source role")
            trio.run(setup_source_node, args.relay_addr, args.dest_id, args.seed)
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main() 
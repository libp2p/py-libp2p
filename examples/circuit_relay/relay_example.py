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
    python relay_example.py --role source \
        --relay-addr RELAY_PEER_ID \
        --dest-id DESTINATION_PEER_ID
"""

import argparse
import logging
import os
import sys

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID,
    STOP_PROTOCOL_ID,
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.resources import RelayLimits
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.tools.async_service import background_trio_service
from libp2p.utils.logging import setup_logging as libp2p_setup_logging

# Configure logging (default console for this example)
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
    remote_peer_id = stream.muxed_conn.peer_id
    try:
        remote_addr = stream.get_remote_address()
    except Exception:
        remote_addr = None
    logger.debug(
        "[APP] handle_example_protocol: incoming stream |",
        "remote_peer=%s | remote_addr=%s | protocol=%s",
        remote_peer_id,
        remote_addr,
        getattr(stream, "protocol_id", None),
    )

    try:
        # Read the incoming message
        logger.debug("[APP] waiting to read up to %s bytes from stream", MAX_READ_LEN)
        msg = await stream.read(MAX_READ_LEN)
        if msg:
            logger.info(
                "Received message (%d bytes): %s", len(msg), msg.decode(errors="ignore")
            )

        # Send a response
        # Get the local peer ID from the secure connection
        local_peer_id = stream.muxed_conn.peer_id
        response = f"Hello! This is {local_peer_id}".encode()
        logger.debug("[APP] writing %d bytes to stream", len(response))
        await stream.write(response)
        logger.info("Sent response to %s", remote_peer_id)
    except Exception as e:
        logger.exception("[APP] Error handling stream: %s", e)
    finally:
        try:
            await stream.close()
            logger.debug("[APP] stream closed")
        except Exception:
            logger.debug("[APP] stream close raised, attempting reset")
            try:
                await stream.reset()
            except Exception:
                pass


async def setup_relay_node(port: int, seed: int | None = None) -> None:
    """Set up and run a relay node."""
    logger.info("Starting relay node...")

    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    logger.debug("[RELAY] created key_pair=%s", type(key_pair).__name__)
    host = new_host(key_pair=key_pair)
    logger.debug("[RELAY] host initialized | peer_id=%s", host.get_id())

    # Configure the relay
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )

    relay_config = RelayConfig(
        roles=RelayRole.HOP | RelayRole.STOP | RelayRole.CLIENT,  # All capabilities
        limits=limits,
    )

    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=True)
    logger.debug(
        "[RELAY] CircuitV2Protocol initialized | allow_hop=%s |",
        "limits(duration=%s,data=%s,max_circuit_conns=%s,max_reservations=%s)",
        True,
        limits.duration,
        limits.data,
        limits.max_circuit_conns,
        limits.max_reservations,
    )

    # Start the host
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run(listen_addrs=[listen_addr]):
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Relay node started with ID: {peer_id}")

        addrs = host.get_addrs()
        for addr in addrs:
            logger.info(f"Listening on: {addr}")

        # Register protocol handlers
        logger.debug("[RELAY] registering stream handlers")
        host.set_stream_handler(EXAMPLE_PROTOCOL_ID, handle_example_protocol)
        host.set_stream_handler(PROTOCOL_ID, protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTOCOL_ID, protocol._handle_stop_stream)
        logger.debug("[RELAY] protocol handlers registered")

        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")

            # Create and register the transport
            CircuitV2Transport(host, protocol, relay_config)
            logger.info(
                "Circuit relay transport initialized | ",
                "enable_hop=%r enable_stop=%r enable_client=%r",
                relay_config.enable_hop,
                relay_config.enable_stop,
                relay_config.enable_client,
            )

            print("\nRelay node is running. Use the following address to connect:")
            print(f"{addrs[0]}")
            print("\nPress Ctrl+C to exit\n")

            # Keep the relay running
            await trio.sleep_forever()


async def setup_destination_node(
    port: int, relay_addr: str, seed: int | None = None
) -> None:
    """Set up and run a destination node that accepts incoming connections."""
    logger.info("Starting destination node...")

    # Create host with a fixed key if seed is provided
    key_pair = create_new_key_pair(generate_fixed_private_key(seed) if seed else None)
    host = new_host(key_pair=key_pair)
    logger.debug("[DEST] host initialized | peer_id=%s", host.get_id())

    # Configure the circuit relay client
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )

    relay_config = RelayConfig(
        roles=RelayRole.STOP | RelayRole.CLIENT,  # Accept connections and use relays
        limits=limits,
    )

    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=False)
    logger.debug(
        "[DEST] CircuitV2Protocol initialized | allow_hop=%s |",
        "limits(duration=%s,data=%s,max_circuit_conns=%s,max_reservations=%s)",
        False,
        limits.duration,
        limits.data,
        limits.max_circuit_conns,
        limits.max_reservations,
    )

    # Start the host
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with host.run(listen_addrs=[listen_addr]):
        # Print information about this node
        peer_id = host.get_id()
        logger.info(f"Destination node started with ID: {peer_id}")

        addrs = host.get_addrs()
        for addr in addrs:
            logger.info(f"Listening on: {addr}")

        # Register protocol handlers
        logger.debug("[DEST] registering stream handlers")
        host.set_stream_handler(EXAMPLE_PROTOCOL_ID, handle_example_protocol)
        host.set_stream_handler(PROTOCOL_ID, protocol._handle_hop_stream)
        host.set_stream_handler(STOP_PROTOCOL_ID, protocol._handle_stop_stream)
        logger.debug("[DEST] protocol handlers registered")

        # Start the relay protocol service
        async with background_trio_service(protocol):
            logger.info("Circuit relay protocol started")

            # Create and initialize transport
            transport = CircuitV2Transport(host, protocol, relay_config)
            logger.info(
                "Circuit relay transport initialized | ",
                "enable_hop=%r enable_stop=%r enable_client=%r",
                relay_config.enable_hop,
                relay_config.enable_stop,
                relay_config.enable_client,
            )

            # Create discovery service
            discovery = RelayDiscovery(host, auto_reserve=True)
            transport.discovery = discovery
            logger.info(
                "[DEST] Relay discovery service created | auto_reserve=%s",
                True,
            )

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
                            relay_peer_id = ID.from_string(relay_addr)
                            relay_info = PeerInfo(
                                relay_peer_id,
                                [
                                    multiaddr.Multiaddr(
                                        f"/ip4/127.0.0.1/tcp/8000/p2p/{relay_addr}"
                                    )
                                ],
                            )
                            logger.info(
                                f"Using constructed address: {relay_info.addrs[0]}"
                            )

                        logger.debug(
                            "[DEST] attempting host.connect to relay %s",
                            relay_info.peer_id,
                        )
                        await host.connect(relay_info)
                        logger.info(f"Connected to relay {relay_info.peer_id}")
                        try:
                            connected = host.is_peer_connected(relay_info.peer_id)  # type: ignore[attr-defined]
                            logger.debug("[DEST] relay connected? %s", connected)
                        except Exception:
                            pass
                    except Exception as e:
                        logger.exception("[DEST] Failed to connect to relay: %s", e)
                        return

        print("\nDestination node is running with peer ID:")
        print(f"{peer_id}")
        print("\nPress Ctrl+C to exit\n")

        # Keep the node running
        await trio.sleep_forever()


async def setup_source_node(
    relay_addr: str, dest_id: str, seed: int | None = None
) -> None:
    """
    Set up and run a source node that connects to the destination
    through the relay.
    """
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
    logger.debug("[SRC] host initialized | peer_id=%s", host.get_id())

    # Configure the circuit relay client
    limits = RelayLimits(
        duration=3600,  # 1 hour
        data=1024 * 1024 * 100,  # 100 MB
        max_circuit_conns=10,
        max_reservations=5,
    )

    relay_config = RelayConfig(
        roles=RelayRole.STOP | RelayRole.CLIENT,  # Accept connections and use relays
        limits=limits,
    )

    # Initialize the protocol
    protocol = CircuitV2Protocol(host, limits=limits, allow_hop=False)
    logger.debug(
        "[SRC] CircuitV2Protocol initialized | allow_hop=%s |",
        "limits(duration=%d, data=%d, max_circuit_conns=%d, max_reservations=%d)",
        False,
        limits.duration,
        limits.data,
        limits.max_circuit_conns,
        limits.max_reservations,
    )

    # Start the host
    async with host.run(
        listen_addrs=[multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")]
    ):  # Use ephemeral port
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
            logger.info(
                "Circuit relay transport initialized | ",
                "enable_hop=%r enable_stop=%r enable_client=%r",
                relay_config.enable_hop,
                relay_config.enable_stop,
                relay_config.enable_client,
            )

            # Create discovery service
            discovery = RelayDiscovery(host, auto_reserve=True)
            transport.discovery = discovery
            logger.info(
                "[SRC] Relay discovery service created | auto_reserve=%s",
                True,
            )

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
                        relay_peer_id = ID.from_string(relay_addr)
                        relay_info = PeerInfo(
                            relay_peer_id,
                            [
                                multiaddr.Multiaddr(
                                    f"/ip4/127.0.0.1/tcp/8000/p2p/{relay_addr}"
                                )
                            ],
                        )
                        logger.info(f"Using constructed address: {relay_info.addrs[0]}")

                    logger.debug(
                        "[SRC] attempting host.connect to relay %s", relay_info.peer_id
                    )
                    await host.connect(relay_info)
                    logger.info(f"Connected to relay {relay_info.peer_id}")
                    try:
                        connected = host.is_peer_connected(relay_info.peer_id)  # type: ignore[attr-defined]
                        logger.debug("[SRC] relay connected? %s", connected)
                    except Exception:
                        pass

                    # Wait for relay discovery to find the relay
                    await trio.sleep(2)
                    try:
                        relays = transport.discovery.get_relays()
                        logger.debug("[SRC] discovered relays: %s", relays)
                    except Exception:
                        pass

                    # Convert destination ID string to peer ID
                    dest_peer_id = ID.from_string(dest_id)

                    # Try to connect to the destination through the relay
                    logger.info(
                        f"Connecting to destination {dest_peer_id} through relay"
                    )

                    # Create peer info with relay
                    relay_peer_id = relay_info.peer_id
                    logger.info(f"This is the relay peer id: {relay_peer_id}")

                    # Create a proper peer info with a relay address
                    # The destination peer should be reachable through a
                    # p2p-circuit address
                    circuit_addr = multiaddr.Multiaddr(
                        f"{relay_info.addrs[0]}/p2p-circuit/p2p/{dest_peer_id}"
                    )
                    dest_peer_info = PeerInfo(dest_peer_id, [circuit_addr])
                    logger.info(f"This is the dest peer info: {dest_peer_info}")

                    # Dial through the relay
                    try:
                        logger.info(
                            f"Attempting to dial destination {dest_peer_id} "
                            f"through relay {relay_peer_id}"
                        )

                        logger.debug(
                            "[SRC] dialing via transport: dest=%s relay=%s",
                            dest_peer_id,
                            relay_peer_id,
                        )
                        connection = await transport.dial(circuit_addr)
                        logger.info("Established relay RawConnection: %s", connection)

                        logger.info(
                            "Successfully connected to destination through relay!"
                        )

                        # Open a stream to our example protocol
                        logger.debug(
                            "[SRC] opening app stream to %s with %s",
                            dest_peer_id,
                            EXAMPLE_PROTOCOL_ID,
                        )
                        stream = await host.new_stream(
                            dest_peer_id, [EXAMPLE_PROTOCOL_ID]
                        )
                        if stream:
                            logger.info(
                                f"Opened stream to destination with protocol "
                                f"{EXAMPLE_PROTOCOL_ID}"
                            )

                            # Send a message
                            msg = f"Hello from {peer_id}!".encode()
                            logger.debug(
                                "[SRC] writing %d bytes on app stream", len(msg)
                            )
                            await stream.write(msg)
                            logger.info("Sent message to destination")

                            # Wait for response
                            logger.debug(
                                "[SRC] waiting to read up to %d bytes on app stream",
                                MAX_READ_LEN,
                            )
                            response = await stream.read(MAX_READ_LEN)
                            logger.info(
                                f"Received response: "
                                f"{response.decode() if response else 'No response'}"
                            )

                            # Close the stream
                            await stream.close()
                        else:
                            logger.error("Failed to open stream to destination")
                    except Exception as e:
                        logger.exception("[SRC] Failed to dial through relay: %s", e)
                        logger.error(f"Exception type: {type(e).__name__}")
                        raise

                except Exception as e:
                    logger.exception("[SRC] Error: %s", e)

                print("\nSource operation completed")
                # Keep running for a bit to allow messages to be processed
                await trio.sleep(5)


def generate_fixed_private_key(seed: int | None) -> bytes:
    """Generate a fixed private key from a seed for reproducible peer IDs."""
    import random

    if seed is None:
        # Generate random bytes if no seed provided
        return random.getrandbits(32 * 8).to_bytes(length=32, byteorder="big")

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

    # Set log level and libp2p structured logging
    if args.debug:
        # Enable verbose console logs
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("libp2p").setLevel(logging.DEBUG)
        # Also enable libp2p file+console logging via env control, if not set
        os.environ.setdefault("LIBP2P_DEBUG", "DEBUG")
        try:
            libp2p_setup_logging()
            logger.debug("libp2p logging initialized via utils.logging.setup_logging")
        except Exception as e:
            logger.debug(
                "libp2p logging setup failed: %s — continuing with basicConfig", e
            )

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

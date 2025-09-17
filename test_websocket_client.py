#!/usr/bin/env python3
"""
Standalone WebSocket client for testing py-libp2p WebSocket transport.
This script allows you to test the Python WebSocket client independently.
"""

import argparse
import logging
import sys

from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.exceptions import SwarmException
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.transport.websocket.multiaddr_utils import (
    is_valid_websocket_multiaddr,
    parse_websocket_multiaddr,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Enable debug logging for WebSocket transport
logging.getLogger("libp2p.transport.websocket").setLevel(logging.DEBUG)
logging.getLogger("libp2p.network.swarm").setLevel(logging.DEBUG)

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")


async def test_websocket_connection(destination: str, timeout: int = 30) -> bool:
    """
    Test WebSocket connection to a destination multiaddr.

    Args:
        destination: Multiaddr string (e.g., /ip4/127.0.0.1/tcp/8080/ws/p2p/...)
        timeout: Connection timeout in seconds

    Returns:
        True if connection successful, False otherwise

    """
    try:
        # Parse the destination multiaddr
        maddr = Multiaddr(destination)
        logger.info(f"Testing connection to: {maddr}")

        # Validate WebSocket multiaddr
        if not is_valid_websocket_multiaddr(maddr):
            logger.error(f"Invalid WebSocket multiaddr: {maddr}")
            return False

        # Parse WebSocket multiaddr
        try:
            parsed = parse_websocket_multiaddr(maddr)
            logger.info(
                f"Parsed WebSocket multiaddr: is_wss={parsed.is_wss}, sni={parsed.sni}, rest_multiaddr={parsed.rest_multiaddr}"
            )
        except Exception as e:
            logger.error(f"Failed to parse WebSocket multiaddr: {e}")
            return False

        # Extract peer ID from multiaddr
        try:
            peer_id = ID.from_base58(maddr.value_for_protocol("p2p"))
            logger.info(f"Target peer ID: {peer_id}")
        except Exception as e:
            logger.error(f"Failed to extract peer ID from multiaddr: {e}")
            return False

        # Create Python host using professional pattern
        logger.info("Creating Python host...")
        key_pair = create_new_key_pair()
        py_peer_id = ID.from_pubkey(key_pair.public_key)
        logger.info(f"Python Peer ID: {py_peer_id}")

        # Generate X25519 keypair for Noise
        noise_key_pair = create_new_x25519_key_pair()

        # Create security options (following professional pattern)
        security_options = {
            NOISE_PROTOCOL_ID: NoiseTransport(
                libp2p_keypair=key_pair,
                noise_privkey=noise_key_pair.private_key,
                early_data=None,
                with_noise_pipes=False,
            )
        }

        # Create muxer options
        muxer_options = create_yamux_muxer_option()

        # Create host with proper configuration
        host = new_host(
            key_pair=key_pair,
            sec_opt=security_options,
            muxer_opt=muxer_options,
            listen_addrs=[
                Multiaddr("/ip4/0.0.0.0/tcp/0/ws")
            ],  # WebSocket listen address
        )
        logger.info(f"Python host created: {host}")

        # Create peer info using professional helper
        peer_info = info_from_p2p_addr(maddr)
        logger.info(f"Connecting to: {peer_info}")

        # Start the host
        logger.info("Starting host...")
        async with host.run(listen_addrs=[]):
            # Wait a moment for host to be ready
            await trio.sleep(1)

            # Attempt connection with timeout
            logger.info("Attempting to connect...")
            try:
                with trio.fail_after(timeout):
                    await host.connect(peer_info)
                logger.info("✅ Successfully connected to peer!")

                # Test ping protocol (following professional pattern)
                logger.info("Testing ping protocol...")
                try:
                    stream = await host.new_stream(
                        peer_info.peer_id, [PING_PROTOCOL_ID]
                    )
                    logger.info("✅ Successfully created ping stream!")

                    # Send ping (32 bytes as per libp2p ping protocol)
                    ping_data = b"\x01" * 32
                    await stream.write(ping_data)
                    logger.info(f"✅ Sent ping: {len(ping_data)} bytes")

                    # Wait for pong (should be same 32 bytes)
                    pong_data = await stream.read(32)
                    logger.info(f"✅ Received pong: {len(pong_data)} bytes")

                    if pong_data == ping_data:
                        logger.info("✅ Ping-pong test successful!")
                        return True
                    else:
                        logger.error(
                            f"❌ Unexpected pong data: expected {len(ping_data)} bytes, got {len(pong_data)} bytes"
                        )
                        return False

                except Exception as e:
                    logger.error(f"❌ Ping protocol test failed: {e}")
                    return False

            except trio.TooSlowError:
                logger.error(f"❌ Connection timeout after {timeout} seconds")
                return False
            except SwarmException as e:
                logger.error(f"❌ Connection failed with SwarmException: {e}")
                # Log the underlying error details
                if hasattr(e, "__cause__") and e.__cause__:
                    logger.error(f"Underlying error: {e.__cause__}")
                return False
            except Exception as e:
                logger.error(f"❌ Connection failed with unexpected error: {e}")
                import traceback

                logger.error(f"Full traceback: {traceback.format_exc()}")
                return False

    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        return False


async def main():
    """Main function to run the WebSocket client test."""
    parser = argparse.ArgumentParser(
        description="Test py-libp2p WebSocket client connection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test connection to a WebSocket peer
  python test_websocket_client.py /ip4/127.0.0.1/tcp/8080/ws/p2p/12D3KooW...

  # Test with custom timeout
  python test_websocket_client.py /ip4/127.0.0.1/tcp/8080/ws/p2p/12D3KooW... --timeout 60

  # Test WSS connection
  python test_websocket_client.py /ip4/127.0.0.1/tcp/8080/wss/p2p/12D3KooW...
        """,
    )

    parser.add_argument(
        "destination",
        help="Destination multiaddr (e.g., /ip4/127.0.0.1/tcp/8080/ws/p2p/12D3KooW...)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Connection timeout in seconds (default: 30)",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    logger.info("🚀 Starting WebSocket client test...")
    logger.info(f"Destination: {args.destination}")
    logger.info(f"Timeout: {args.timeout}s")

    # Run the test
    success = await test_websocket_connection(args.destination, args.timeout)

    if success:
        logger.info("🎉 WebSocket client test completed successfully!")
        sys.exit(0)
    else:
        logger.error("💥 WebSocket client test failed!")
        sys.exit(1)


if __name__ == "__main__":
    # Run with trio
    trio.run(main)

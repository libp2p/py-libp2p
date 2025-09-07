#!/usr/bin/env python3
"""
Debug script to test WebSocket URL construction and basic connection.
"""

import logging

from multiaddr import Multiaddr

from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def test_websocket_url():
    """Test WebSocket URL construction."""
    # Test multiaddr from your JS node
    maddr_str = "/ip4/127.0.0.1/tcp/35391/ws/p2p/12D3KooWQh7p5xP2ppr3CrhUFsawmsKNe9jgDbacQdWCYpuGfMVN"
    maddr = Multiaddr(maddr_str)

    logger.info(f"Testing multiaddr: {maddr}")

    # Parse WebSocket multiaddr
    parsed = parse_websocket_multiaddr(maddr)
    logger.info(
        f"Parsed: is_wss={parsed.is_wss}, sni={parsed.sni}, rest_multiaddr={parsed.rest_multiaddr}"
    )

    # Construct WebSocket URL
    if parsed.is_wss:
        protocol = "wss"
    else:
        protocol = "ws"

    # Extract host and port from rest_multiaddr
    host = parsed.rest_multiaddr.value_for_protocol("ip4")
    port = parsed.rest_multiaddr.value_for_protocol("tcp")

    websocket_url = f"{protocol}://{host}:{port}/"
    logger.info(f"WebSocket URL: {websocket_url}")

    # Test basic WebSocket connection
    try:
        from trio_websocket import open_websocket_url

        logger.info("Testing basic WebSocket connection...")
        async with open_websocket_url(websocket_url) as ws:
            logger.info("✅ WebSocket connection successful!")
            # Send a simple message
            await ws.send_message(b"test")
            logger.info("✅ Message sent successfully!")

    except Exception as e:
        logger.error(f"❌ WebSocket connection failed: {e}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    import trio

    trio.run(test_websocket_url)

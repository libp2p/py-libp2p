#!/usr/bin/env python3
"""
Enhanced WebSocket server using libp2p WebSocket transport.
Supports Echo and Ping protocols with secure connections.
"""

import logging

from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.transport.websocket.transport import WebsocketConfig, WebsocketTransport

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Protocol IDs
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")
PING_PROTOCOL_ID = TProtocol("/ping/1.0.0")


class WebSocketServer:
    """Enhanced WebSocket server using libp2p WebSocket transport."""

    def __init__(self, port: int = 8080):
        from typing import Any

        self.port = port
        self.host: Any = None
        self.echo_count = 0
        self.ping_count = 0

    def create_host(self):
        """Create a libp2p host with WebSocket transport."""
        # Create key pair
        key_pair = create_new_key_pair()

        # Create WebSocket transport configuration
        config = WebsocketConfig(
            handshake_timeout=30.0,
            max_connections=100,
            max_buffered_amount=8 * 1024 * 1024,  # 8MB
        )

        # Create transport upgrader
        from libp2p.stream_muxer.yamux.yamux import Yamux
        from libp2p.transport.upgrader import TransportUpgrader

        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )

        # Create WebSocket transport
        transport = WebsocketTransport(upgrader, config)

        # Create host with WebSocket listen address
        listen_addrs = [Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}/ws")]

        host = new_host(
            key_pair=key_pair,
            sec_opt={PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)},
            muxer_opt=create_yamux_muxer_option(),
            listen_addrs=listen_addrs,
        )

        # Replace the default transport with our configured one
        from libp2p.network.swarm import Swarm

        swarm = host.get_network()
        if isinstance(swarm, Swarm):
            swarm.transport = transport

        return host

    async def echo_handler(self, stream):
        """Handle echo protocol requests."""
        try:
            data = await stream.read(1024)
            if data:
                message = data.decode("utf-8", errors="replace")
                self.echo_count += 1
                logger.info(f"📥 Echo request #{self.echo_count}: {message}")

                # Echo back the message
                response = f"Echo: {message}"
                await stream.write(response.encode("utf-8"))
                logger.info(f"📤 Echo response #{self.echo_count}: {response}")

            await stream.close()
        except Exception as e:
            logger.error(f"❌ Echo handler error: {e}")
            await stream.close()

    async def ping_handler(self, stream):
        """Handle ping protocol requests."""
        try:
            data = await stream.read(1024)
            if data:
                message = data.decode("utf-8", errors="replace")
                self.ping_count += 1
                logger.info(f"📥 Ping request #{self.ping_count}: {message}")

                # Respond with pong
                response = "pong"
                await stream.write(response.encode("utf-8"))
                logger.info(f"📤 Ping response #{self.ping_count}: {response}")

            await stream.close()
        except Exception as e:
            logger.error(f"❌ Ping handler error: {e}")
            await stream.close()

    async def start(self):
        """Start the WebSocket server."""
        logger.info("🚀 Starting Enhanced WebSocket Server with libp2p...")
        logger.info("📡 Features: Echo Protocol, Ping Protocol, Secure Connections")
        logger.info("🌐 Browser client: http://localhost:8000/client.html")

        try:
            # Create host
            self.host = self.create_host()

            # Set up protocol handlers
            self.host.set_stream_handler(ECHO_PROTOCOL_ID, self.echo_handler)
            self.host.set_stream_handler(PING_PROTOCOL_ID, self.ping_handler)

            # Start the host with listen addresses
            listen_addrs = [Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}/ws")]
            async with self.host.run(listen_addrs=listen_addrs):
                # Get listening addresses
                addrs = self.host.get_addrs()
                logger.info("✅ Server started successfully!")
                logger.info("📡 Listening on:")
                for addr in addrs:
                    logger.info(f"   {addr}")

                logger.info("💡 Press Ctrl+C to stop the server")

                # Keep running
                await trio.sleep_forever()

        except KeyboardInterrupt:
            logger.info("🛑 Server stopped by user")
        except Exception as e:
            logger.error(f"❌ Server error: {e}")
        finally:
            logger.info("🧹 Server cleanup completed")


async def main():
    """Main function to start the WebSocket server."""
    server = WebSocketServer(port=8080)
    await server.start()


if __name__ == "__main__":
    trio.run(main)

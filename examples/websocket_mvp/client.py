#!/usr/bin/env python3
"""
Enhanced WebSocket client using libp2p WebSocket transport.
Tests Echo and Ping protocols with secure connections.
Includes HTML server for browser client.
"""

import http.server
import logging
import os
from pathlib import Path
import socketserver
import threading
import time
from typing import Any

from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
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


class HTMLServer:
    """Simple HTTP server for serving HTML files."""

    def __init__(self, port: int = 8000):
        self.port = port
        self.server: socketserver.TCPServer | None = None
        self.thread: threading.Thread | None = None
        self.running = False

    def start(self):
        """Start the HTML server in a separate thread."""
        if self.running:
            logger.warning("HTML server is already running")
            return

        def run_server():
            # Change to the directory containing HTML files
            html_dir = Path(__file__).parent
            os.chdir(html_dir)

            # Create HTTP server
            handler = http.server.SimpleHTTPRequestHandler

            with socketserver.TCPServer(("", self.port), handler) as httpd:
                self.server = httpd
                self.running = True
                logger.info(f"🌐 HTML server started on http://localhost:{self.port}")
                logger.info(f"📁 Serving from: {html_dir}")
                logger.info(
                    f"📄 Browser client: http://localhost:{self.port}/client.html"
                )

                try:
                    httpd.serve_forever()
                except Exception as e:
                    logger.error(f"HTML server error: {e}")
                finally:
                    self.running = False

        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        logger.info("✅ HTML server started in background")

    def stop(self):
        """Stop the HTML server."""
        if self.server and self.running:
            self.server.shutdown()
            self.running = False
            logger.info("🛑 HTML server stopped")


class WebSocketClient:
    """Enhanced WebSocket client using libp2p WebSocket transport."""

    def __init__(self):
        self.host: Any = None
        self.echo_tests = 0
        self.ping_tests = 0
        self.html_server = HTMLServer()

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

        # Create host
        host = new_host(
            key_pair=key_pair,
            sec_opt={PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)},
            muxer_opt=create_yamux_muxer_option(),
            listen_addrs=[],  # Client doesn't need to listen
        )

        # Replace the default transport with our configured one
        from libp2p.network.swarm import Swarm

        swarm = host.get_network()
        if isinstance(swarm, Swarm):
            swarm.transport = transport

        return host

    async def send_echo(self, peer_info, message: str) -> str:
        """Send an echo message and return the response."""
        try:
            logger.info(f"📤 Sending echo: {message}")

            # Open stream to echo protocol
            stream = await self.host.new_stream(peer_info.peer_id, [ECHO_PROTOCOL_ID])

            # Send message
            await stream.write(message.encode("utf-8"))
            await stream.close()

            # Read response
            response_data = await stream.read(1024)
            response = response_data.decode("utf-8", errors="replace")

            logger.info(f"📥 Echo response: {response}")
            return response

        except Exception as e:
            logger.error(f"❌ Echo error: {e}")
            raise

    async def send_ping(self, peer_info) -> str:
        """Send a ping message and return the response."""
        try:
            logger.info("📤 Sending ping")
            start_time = time.time()

            # Open stream to ping protocol
            stream = await self.host.new_stream(peer_info.peer_id, [PING_PROTOCOL_ID])

            # Send ping
            await stream.write(b"ping")
            await stream.close()

            # Read response
            response_data = await stream.read(1024)
            response = response_data.decode("utf-8", errors="replace")

            end_time = time.time()
            latency = (end_time - start_time) * 1000

            logger.info(f"📥 Ping response: {response} (Latency: {latency:.2f}ms)")
            return response

        except Exception as e:
            logger.error(f"❌ Ping error: {e}")
            raise

    async def connect_and_test(self, server_addr: str):
        """Connect to server and run tests."""
        try:
            logger.info("🚀 Starting WebSocket Client Tests...")
            logger.info("📡 Testing Echo and Ping protocols with libp2p")

            # Create host
            self.host = self.create_host()

            # Start the host
            async with self.host.run(listen_addrs=[]):
                logger.info("✅ Client host started")

                # Parse server address
                server_maddr = Multiaddr(server_addr)
                peer_info = info_from_p2p_addr(server_maddr)

                logger.info(f"🔌 Connecting to server: {server_addr}")

                # Connect to server
                await self.host.connect(peer_info)
                logger.info(f"✅ Connected to server {peer_info.peer_id}")

                # Test Echo Protocol
                logger.info("\n🔄 Testing Echo Protocol...")
                self.echo_tests += 1
                echo_response = await self.send_echo(
                    peer_info, "Hello libp2p WebSocket!"
                )
                if "Echo: Hello libp2p WebSocket!" in echo_response:
                    logger.info("✅ Echo test passed!")
                else:
                    logger.error("❌ Echo test failed!")

                # Test Ping Protocol
                logger.info("\n🔄 Testing Ping Protocol...")
                self.ping_tests += 1
                ping_response = await self.send_ping(peer_info)
                if ping_response == "pong":
                    logger.info("✅ Ping test passed!")
                else:
                    logger.error("❌ Ping test failed!")

                # Test multiple echoes
                logger.info("\n🔄 Testing multiple echoes...")
                for i in range(3):
                    self.echo_tests += 1
                    await self.send_echo(peer_info, f"Test message {i + 1}")
                    await trio.sleep(0.5)

                logger.info("🎉 All tests completed!")
                logger.info(
                    f"📊 Statistics: {self.echo_tests} echo tests, "
                    f"{self.ping_tests} ping tests"
                )

        except Exception as e:
            logger.error(f"❌ Client error: {e}")
        finally:
            if self.host:
                await self.host.stop()
                logger.info("🧹 Client cleanup completed")

    async def start_with_html_server(self):
        """Start client with HTML server for browser testing."""
        logger.info("🚀 Starting Enhanced WebSocket Client with HTML Server...")
        logger.info("📡 Features: Echo Protocol, Ping Protocol, Browser Client")

        # Start HTML server
        self.html_server.start()

        logger.info("✅ HTML server started")
        logger.info("🌐 Browser client available at: http://localhost:8000/client.html")
        logger.info("💡 Instructions:")
        logger.info("   1. Start the server: python server.py")
        logger.info("   2. Copy the server's full multiaddr from the logs")
        logger.info("   3. Open browser: http://localhost:8000/client.html")
        logger.info("   4. Enter the server multiaddr and test Echo/Ping protocols")
        logger.info(
            "   5. Or run automated tests by updating server_addr in this script"
        )

        # Keep running to serve HTML
        try:
            await trio.sleep_forever()
        except KeyboardInterrupt:
            logger.info("🛑 Client stopped by user")
        finally:
            self.html_server.stop()
            logger.info("🧹 HTML server stopped")


async def main():
    """Main function to run the client."""
    client = WebSocketClient()

    # You can choose between:
    # 1. Start with HTML server for browser testing
    # 2. Run automated tests with a specific server address

    # Option 1: Start with HTML server (default)
    await client.start_with_html_server()

    # Option 2: Run automated tests (uncomment and update server_addr)
    # server_addr = "/ip4/127.0.0.1/tcp/8080/ws/p2p/12D3KooWExample"  # noqa: E501
    # await client.connect_and_test(server_addr)


if __name__ == "__main__":
    trio.run(main)

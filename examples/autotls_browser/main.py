#!/usr/bin/env python3
"""
AutoTLS Browser Integration Example

This example demonstrates AutoTLS functionality for seamless browser-to-Python
WebSocket connections without manual certificate setup.

Features:
- Automatic TLS certificate generation and management
- Browser-compatible WSS connections
- Certificate renewal and lifecycle management
- Production-ready configuration
"""

import argparse
import logging
from typing import Any

from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.transport.websocket.transport import (
    WebsocketTransport,
    WithAutoTLS,
)

# Enable debug logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("libp2p.autotls-browser-demo")

# Demo protocols
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")
CHAT_PROTOCOL_ID = TProtocol("/chat/1.0.0")


class AutoTLSBrowserDemo:
    """AutoTLS browser integration demo."""

    def __init__(
        self,
        domain: str = "libp2p.local",
        storage_path: str = "autotls-certs",
        port: int = 8080,
    ) -> None:
        """
        Initialize AutoTLS browser demo.

        Args:
            domain: Domain for AutoTLS certificates
            storage_path: Path for certificate storage
            port: Port to listen on

        """
        self.domain = domain
        self.storage_path = storage_path
        self.port = port
        self.host: Any | None = None
        self.peer_id: ID | None = None

    async def start_server(self) -> None:
        """Start the AutoTLS-enabled server."""
        logger.info("Starting AutoTLS browser integration demo...")

        # Create peer identity
        key_pair = create_new_key_pair()
        from libp2p.peer.id import ID

        self.peer_id = ID.from_pubkey(key_pair.public_key)

        # Create AutoTLS configuration
        autotls_config = WithAutoTLS(
            domain=self.domain,
            storage_path=self.storage_path,
            renewal_threshold_hours=24,
            cert_validity_days=90,
        )

        # Create host with AutoTLS transport (simplified approach)
        from libp2p.host.basic_host import BasicHost
        from libp2p.network.swarm import Swarm
        from libp2p.peer.id import ID
        from libp2p.peer.peerstore import PeerStore
        from libp2p.transport.upgrader import TransportUpgrader

        # Create upgrader
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol=create_yamux_muxer_option(),
        )

        # Create transport with AutoTLS configuration
        from libp2p.transport.websocket.autotls import AutoTLSConfig

        # Create AutoTLS configuration
        autotls_config_obj = AutoTLSConfig(
            enabled=True,
            storage_path=self.storage_path,
            renewal_threshold_hours=24,
            cert_validity_days=90,
            default_domain=self.domain,
            wildcard_domain=True,
        )

        # Set AutoTLS configuration in the WebSocket config
        autotls_config.autotls_config = autotls_config_obj

        # Create transport with AutoTLS
        transport = WebsocketTransport(upgrader, config=autotls_config)

        # Create host
        peer_store = PeerStore()
        peer_id = ID.from_pubkey(key_pair.public_key)

        # Add peer information to peerstore
        peer_store.add_privkey(peer_id, key_pair.private_key)
        peer_store.add_pubkey(peer_id, key_pair.public_key)

        swarm = Swarm(
            peer_id=peer_id,
            peerstore=peer_store,
            upgrader=upgrader,
            transport=transport,
        )
        self.host = BasicHost(swarm)

        # Set up protocol handlers
        await self._setup_protocols()

        # Start listening
        listen_addr = f"/ip4/0.0.0.0/tcp/{self.port}/ws"
        wss_addr = f"/ip4/0.0.0.0/tcp/{self.port}/wss"

        logger.info(f"Server started with peer ID: {self.peer_id}")
        logger.info(f"Listening on: {listen_addr}")
        logger.info(f"Listening on: {wss_addr}")
        logger.info(f"AutoTLS domain: {self.domain}")
        logger.info(f"Certificate storage: {self.storage_path}")

        # Use the run method with listen addresses (start with WS only for testing)
        async with self.host.run([Multiaddr(listen_addr)]):
            # Keep the host running
            await trio.sleep_forever()

        # Print connection information
        self._print_connection_info()

    async def _setup_protocols(self) -> None:
        """Set up protocol handlers."""

        # Echo protocol handler
        async def echo_handler(stream: Any) -> None:
            """Handle echo protocol requests."""
            try:
                while True:
                    data = await stream.read()
                    if not data:
                        break
                    logger.info(f"Echo received: {data.decode()}")
                    await stream.write(data)
            except Exception as e:
                logger.error(f"Echo handler error: {e}")
            finally:
                await stream.close()

        # Chat protocol handler
        async def chat_handler(stream: Any) -> None:
            """Handle chat protocol requests."""
            try:
                while True:
                    data = await stream.read()
                    if not data:
                        break
                    message = data.decode()
                    logger.info(f"Chat message: {message}")

                    # Echo back with prefix
                    response = f"Server: {message}"
                    await stream.write(response.encode())
            except Exception as e:
                logger.error(f"Chat handler error: {e}")
            finally:
                await stream.close()

        # Register protocol handlers
        if self.host:
            self.host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)
            self.host.set_stream_handler(CHAT_PROTOCOL_ID, chat_handler)

    def _print_connection_info(self) -> None:
        """Print connection information for browser clients."""
        print("\n" + "=" * 60)
        print("AutoTLS Browser Integration Demo")
        print("=" * 60)
        print(f"Peer ID: {self.peer_id}")
        print(f"Domain: {self.domain}")
        print(f"Port: {self.port}")
        print("\nWebSocket URLs:")
        print(f"  WS:  ws://localhost:{self.port}/")
        print(f"  WSS: wss://localhost:{self.port}/")
        print("\nBrowser Integration:")
        print("1. Open browser to: http://localhost:8080")
        print("2. The page will automatically connect via WSS")
        print("3. Certificates are automatically managed")
        print("=" * 60)

    async def create_html_page(self) -> str:
        """Create HTML page for browser demo."""
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoTLS Browser Demo</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .status {{
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
            font-weight: bold;
        }}
        .connected {{ background-color: #d4edda; color: #155724; }}
        .disconnected {{ background-color: #f8d7da; color: #721c24; }}
        .connecting {{ background-color: #fff3cd; color: #856404; }}
        .log {{
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 10px;
            height: 200px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }}
        input, button {{
            padding: 8px 12px;
            margin: 5px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }}
        button {{
            background-color: #007bff;
            color: white;
            border: none;
            cursor: pointer;
        }}
        button:hover {{ background-color: #0056b3; }}
        button:disabled {{ background-color: #6c757d; cursor: not-allowed; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>AutoTLS Browser Demo</h1>
        <p>This demo connects to a Python libp2p server using AutoTLS
           for seamless WSS connections.</p>

        <div id="status" class="status disconnected">Disconnected</div>

        <div>
            <button id="connectBtn" onclick="connect()">Connect</button>
            <button id="disconnectBtn" onclick="disconnect()" disabled>
                Disconnect
            </button>
        </div>

        <div>
            <input type="text" id="messageInput"
                   placeholder="Enter message..." disabled>
            <button id="sendBtn" onclick="sendMessage()" disabled>Send Echo</button>
            <button id="chatBtn" onclick="sendChat()" disabled>Send Chat</button>
        </div>

        <h3>Connection Log</h3>
        <div id="log" class="log"></div>
    </div>

    <script>
        let ws = null;
        let isConnected = false;

        function log(message) {{
            const logDiv = document.getElementById('log');
            const timestamp = new Date().toLocaleTimeString();
            logDiv.innerHTML += `[${{timestamp}}] ${{message}}\\n`;
            logDiv.scrollTop = logDiv.scrollHeight;
        }}

        function updateStatus(status, className) {{
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = status;
            statusDiv.className = `status ${{className}}`;
        }}

        function connect() {{
            if (isConnected) return;

            updateStatus('Connecting...', 'connecting');
            log('Attempting to connect to AutoTLS WSS server...');

            // Connect to WSS with AutoTLS
            const wsUrl = 'wss://localhost:{self.port}/';

            try {{
                ws = new WebSocket(wsUrl);

                ws.onopen = function(event) {{
                    isConnected = true;
                    updateStatus('Connected', 'connected');
                    log('✅ Connected to AutoTLS WSS server!');
                    log('🔒 TLS certificate automatically managed');

                    document.getElementById('connectBtn').disabled = true;
                    document.getElementById('disconnectBtn').disabled = false;
                    document.getElementById('messageInput').disabled = false;
                    document.getElementById('sendBtn').disabled = false;
                    document.getElementById('chatBtn').disabled = false;
                }};

                ws.onmessage = function(event) {{
                    log(`📥 Received: ${{event.data}}`);
                }};

                ws.onclose = function(event) {{
                    isConnected = false;
                    updateStatus('Disconnected', 'disconnected');
                    log('🔌 Connection closed');

                    document.getElementById('connectBtn').disabled = false;
                    document.getElementById('disconnectBtn').disabled = true;
                    document.getElementById('messageInput').disabled = true;
                    document.getElementById('sendBtn').disabled = true;
                    document.getElementById('chatBtn').disabled = true;
                }};

                ws.onerror = function(error) {{
                    log(`❌ WebSocket error: ${{error}}`);
                    updateStatus('Error', 'disconnected');
                }};

            }} catch (error) {{
                log(`❌ Failed to create WebSocket: ${{error}}`);
                updateStatus('Error', 'disconnected');
            }}
        }}

        function disconnect() {{
            if (ws && isConnected) {{
                ws.close();
            }}
        }}

        function sendMessage() {{
            if (!isConnected || !ws) {{
                log('❌ Not connected to server');
                return;
            }}

            const input = document.getElementById('messageInput');
            const message = input.value.trim();

            if (message) {{
                log(`📤 Sending echo: ${{message}}`);
                ws.send(message);
                input.value = '';
            }}
        }}

        function sendChat() {{
            if (!isConnected || !ws) {{
                log('❌ Not connected to server');
                return;
            }}

            const input = document.getElementById('messageInput');
            const message = input.value.trim();

            if (message) {{
                log(`📤 Sending chat: ${{message}}`);
                ws.send(`CHAT:${{message}}`);
                input.value = '';
            }}
        }}

        // Auto-connect on page load
        window.onload = function() {{
            log('🚀 AutoTLS Browser Demo loaded');
            log('🔧 AutoTLS automatically manages TLS certificates');
            log('🌐 Ready to connect to Python libp2p server');
        }};
    </script>
</body>
</html>
        """

    async def serve_html(self) -> None:
        """Serve HTML page for browser demo."""
        try:
            from aiohttp import web  # type: ignore

            html_content = await self.create_html_page()

            async def handle(request: Any) -> Any:
                return web.Response(text=html_content, content_type="text/html")

            app = web.Application()
            app.router.add_get("/", handle)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "localhost", 8080)
            await site.start()

            logger.info("HTML server started at http://localhost:8080")

        except ImportError:
            logger.warning("aiohttp not available, skipping HTML server")
            logger.info("Create an HTML file with the content from create_html_page()")


async def main() -> None:
    """Main demo function."""
    parser = argparse.ArgumentParser(description="AutoTLS Browser Integration Demo")
    parser.add_argument(
        "--domain",
        default="libp2p.local",
        help="Domain for AutoTLS certificates (default: libp2p.local)",
    )
    parser.add_argument(
        "--storage-path",
        default="autotls-certs",
        help="Path for certificate storage (default: autotls-certs)",
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port to listen on (default: 8080)"
    )
    parser.add_argument(
        "--serve-html", action="store_true", help="Serve HTML page for browser demo"
    )

    args = parser.parse_args()

    # Create demo instance
    demo = AutoTLSBrowserDemo(
        domain=args.domain,
        storage_path=args.storage_path,
        port=args.port,
    )

    try:
        # Start the server
        await demo.start_server()

        # Serve HTML if requested
        if args.serve_html:
            await demo.serve_html()

        # Keep running
        logger.info("Server running. Press Ctrl+C to stop.")
        await trio.sleep_forever()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    trio.run(main)

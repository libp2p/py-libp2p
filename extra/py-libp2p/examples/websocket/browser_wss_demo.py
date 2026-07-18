#!/usr/bin/env python3
"""
Browser WSS Demo

This example demonstrates browser-to-Python WebSocket connectivity using WSS.
It creates a simple web server that serves an HTML page with JavaScript
that connects to a libp2p WSS server.

Usage:
    python examples/websocket/browser_wss_demo.py
    python examples/websocket/browser_wss_demo.py -p 8443 -w 8080
"""

import argparse
import logging
from pathlib import Path
import sys
import tempfile

from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)

# Enable debug logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("libp2p.browser-wss-demo")

# Simple echo protocol
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


def create_self_signed_certificate():
    """Create a self-signed certificate for WSS testing."""
    try:
        import datetime
        from datetime import timezone
        import ipaddress
        import ssl

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),  # type: ignore
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Test"),  # type: ignore
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),  # type: ignore
                x509.NameAttribute(
                    NameOID.ORGANIZATION_NAME,
                    "libp2p Browser WSS Demo",  # type: ignore
                ),
                x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),  # type: ignore
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(timezone.utc))
            .not_valid_after(
                datetime.datetime.now(timezone.utc) + datetime.timedelta(days=1)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # Create temporary files for cert and key
        cert_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".crt")
        key_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".key")

        # Write certificate and key to files
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        cert_file.close()
        key_file.close()

        # Create SSL contexts
        server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        server_context.load_cert_chain(cert_file.name, key_file.name)

        return server_context, cert_file.name, key_file.name

    except ImportError:
        logger.error("cryptography package required for browser WSS demo")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to create certificates: {e}")
        sys.exit(1)


def cleanup_certificates(cert_file, key_file):
    """Clean up temporary certificate files."""
    try:
        Path(cert_file).unlink(missing_ok=True)
        Path(key_file).unlink(missing_ok=True)
    except Exception:
        pass


async def echo_handler(stream):
    """Simple echo handler that echoes back any data received."""
    try:
        data = await stream.read(1024)
        if data:
            message = data.decode("utf-8", errors="replace")
            logger.info(f"📥 Received from browser: {message}")
            logger.info(f"📤 Echoing back: {message}")
            await stream.write(data)
        await stream.close()
    except Exception as e:
        logger.error(f"Echo handler error: {e}")
        await stream.close()


def create_wss_host(server_context=None):
    """Create a host with WSS transport."""
    # Create key pair and peer store
    key_pair = create_new_key_pair()

    # Create transport upgrader with plaintext security for simplicity

    # Transport upgrader is created but not used in this simplified example

    # Create host with WSS transport
    host = new_host(
        key_pair=key_pair,
        sec_opt={PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)},
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/0.0.0.0/tcp/0/wss")],
        tls_server_config=server_context,
    )

    return host


def create_html_page(wss_url, peer_id):
    """Create HTML page for browser demo."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>libp2p Browser WSS Demo</title>
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
        button {{
            background-color: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            margin: 5px;
        }}
        button:hover {{ background-color: #0056b3; }}
        button:disabled {{ background-color: #6c757d; cursor: not-allowed; }}
        input[type="text"] {{
            width: 100%;
            padding: 8px;
            margin: 5px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
        }}
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
    </style>
</head>
<body>
    <div class="container">
        <h1>🌐 libp2p Browser WSS Demo</h1>
        <p>This demo shows browser-to-Python WebSocket connectivity using WSS.</p>

        <div id="status" class="status disconnected">
            Status: Disconnected
        </div>

        <div>
            <button id="connectBtn" onclick="connect()">Connect to WSS Server</button>
            <button id="disconnectBtn" onclick="disconnect()" disabled>
                Disconnect
            </button>
        </div>

        <div>
            <input
                type="text"
                id="messageInput"
                placeholder="Enter message to send..."
                disabled
            >
            <button id="sendBtn" onclick="sendMessage()" disabled>Send Message</button>
        </div>

        <h3>Connection Info:</h3>
        <p><strong>WSS URL:</strong> <code>{wss_url}</code></p>
        <p><strong>Peer ID:</strong> <code>{peer_id}</code></p>

        <h3>Activity Log:</h3>
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
            statusDiv.textContent = `Status: ${{status}}`;
            statusDiv.className = `status ${{className}}`;
        }}

        function connect() {{
            if (isConnected) return;

            updateStatus('Connecting...', 'connecting');
            log('Attempting to connect to WSS server...');

            // For this demo, we'll use a simple WebSocket connection
            // In a real implementation, you'd use libp2p in the browser
            const wsUrl = '{wss_url}'.replace('wss://', 'wss://').replace('/p2p/', '/');

            try {{
                ws = new WebSocket(wsUrl);

                ws.onopen = function(event) {{
                    isConnected = true;
                    updateStatus('Connected', 'connected');
                    log('✅ Connected to WSS server!');

                    document.getElementById('connectBtn').disabled = true;
                    document.getElementById('disconnectBtn').disabled = false;
                    document.getElementById('messageInput').disabled = false;
                    document.getElementById('sendBtn').disabled = false;
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
                log(`📤 Sending: ${{message}}`);
                ws.send(message);
                input.value = '';
            }}
        }}

        // Allow Enter key to send message
        document.getElementById('messageInput').addEventListener(
            'keypress', function(e) {{
            if (e.key === 'Enter') {{
                sendMessage();
            }}
        }});

        // Initial log message
        log('🚀 Browser WSS Demo ready');
        log('Click "Connect to WSS Server" to start');
    </script>
</body>
</html>
"""


async def run_server(port: int, web_port: int):
    """Run WSS server with web interface."""
    logger.info("🔐 Creating self-signed certificates for WSS...")
    server_context, cert_file, key_file = create_self_signed_certificate()

    try:
        # Create WSS host
        host = create_wss_host(server_context=server_context)

        # Set up echo handler
        host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

        # Start listening
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/wss")

        async with host.run(listen_addrs=[listen_addr]):
            # Get the actual address
            addrs = host.get_addrs()
            if not addrs:
                logger.error("❌ No addresses found for the host")
                return

            server_addr = str(addrs[0])
            wss_url = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")
            peer_id = str(host.get_id())

            # Create HTML page
            html_content = create_html_page(wss_url, peer_id)

            # Start simple HTTP server for the web interface
            import http.server
            import socketserver
            import threading

            class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/" or self.path == "/index.html":
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(html_content.encode())
                    else:
                        super().do_GET()

            # Start HTTP server in a separate thread
            httpd = socketserver.TCPServer(("", web_port), CustomHTTPRequestHandler)
            http_thread = threading.Thread(target=httpd.serve_forever)
            http_thread.daemon = True
            http_thread.start()

            logger.info("🌐 WSS Server with Browser Interface Started!")
            logger.info("=" * 60)
            logger.info(f"📍 WSS Server Address: {wss_url}")
            logger.info(f"🌐 Web Interface: http://localhost:{web_port}")
            logger.info("🔧 Protocol: /echo/1.0.0")
            logger.info("🚀 Transport: WebSocket Secure (WSS)")
            logger.info("🔐 Security: TLS with self-signed certificate")
            logger.info(f"👤 Peer ID: {peer_id}")
            logger.info("")
            logger.info("📋 Open your browser and go to:")
            logger.info(f"   http://localhost:{web_port}")
            logger.info("")
            logger.info("⏳ Waiting for browser connections...")
            logger.info("─" * 60)

            # Wait indefinitely
            await trio.sleep_forever()

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down WSS server...")
    finally:
        cleanup_certificates(cert_file, key_file)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Browser WSS Demo - Browser-to-Python WebSocket connectivity"
    )
    parser.add_argument(
        "-p", "--port", default=8443, type=int, help="WSS server port (default: 8443)"
    )
    parser.add_argument(
        "-w",
        "--web-port",
        default=8080,
        type=int,
        help="Web interface port (default: 8080)",
    )

    args = parser.parse_args()

    trio.run(run_server, args.port, args.web_port)


if __name__ == "__main__":
    main()

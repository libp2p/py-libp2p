"""
Browser Integration for AutoTLS

This module provides browser integration utilities for AutoTLS
WebSocket connections, including HTML generation, JavaScript
clients, and connection management.
"""

import logging
from pathlib import Path

from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.autotls.browser_integration")


class BrowserIntegration:
    """Browser integration utilities for AutoTLS."""

    def __init__(
        self,
        domain: str = "libp2p.local",
        port: int = 8080,
        auto_connect: bool = True,
    ) -> None:
        """
        Initialize browser integration.

        Args:
            domain: Domain for AutoTLS certificates
            port: Port for WebSocket connections
            auto_connect: Whether to auto-connect on page load

        """
        self.domain = domain
        self.port = port
        self.auto_connect = auto_connect

    def generate_html_page(
        self,
        peer_id: ID,
        title: str = "AutoTLS Browser Demo",
        styles: dict[str, str] | None = None,
    ) -> str:
        """
        Generate HTML page for browser integration.

        Args:
            peer_id: Peer ID for connection
            title: Page title
            styles: Custom CSS styles

        Returns:
            HTML page content

        """
        if styles is None:
            styles = self._get_default_styles()

        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        {self._generate_css(styles)}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p>AutoTLS-enabled libp2p WebSocket connection</p>

        <div class="info">
            <h3>Connection Information</h3>
            <p><strong>Peer ID:</strong> <code>{peer_id}</code></p>
            <p><strong>Domain:</strong> <code>{self.domain}</code></p>
            <p><strong>Port:</strong> <code>{self.port}</code></p>
        </div>

        <div id="status" class="status disconnected">Disconnected</div>

        <div class="controls">
            <button id="connectBtn" onclick="connect()">Connect</button>
            <button id="disconnectBtn" onclick="disconnect()" disabled>
                Disconnect
            </button>
            <button id="clearLogBtn" onclick="clearLog()">Clear Log</button>
        </div>

        <div class="input-group">
            <input type="text" id="messageInput"
                   placeholder="Enter message..." disabled>
            <button id="sendBtn" onclick="sendMessage()" disabled>Send Echo</button>
            <button id="chatBtn" onclick="sendChat()" disabled>Send Chat</button>
        </div>

        <div class="protocols">
            <h3>Available Protocols</h3>
            <div class="protocol-list">
                <div class="protocol-item">
                    <strong>/echo/1.0.0</strong> - Echo back received messages
                </div>
                <div class="protocol-item">
                    <strong>/chat/1.0.0</strong> - Chat with server
                </div>
            </div>
        </div>

        <h3>Connection Log</h3>
        <div id="log" class="log"></div>
    </div>

    <script>
        {self._generate_javascript()}
    </script>
</body>
</html>
        """

    def _get_default_styles(self) -> dict[str, str]:
        """Get default CSS styles."""
        return {
            "body": """
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f8f9fa;
                color: #333;
            """,
            "container": """
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            """,
            "status": """
                padding: 15px;
                margin: 15px 0;
                border-radius: 8px;
                font-weight: bold;
                text-align: center;
                font-size: 16px;
            """,
            "connected": """
                background-color: #d4edda;
                color: #155724;
                border: 2px solid #c3e6cb;
            """,
            "disconnected": """
                background-color: #f8d7da;
                color: #721c24;
                border: 2px solid #f5c6cb;
            """,
            "connecting": """
                background-color: #fff3cd;
                color: #856404;
                border: 2px solid #ffeaa7;
            """,
            "controls": """
                display: flex;
                gap: 10px;
                margin: 20px 0;
                flex-wrap: wrap;
            """,
            "input-group": """
                display: flex;
                gap: 10px;
                margin: 20px 0;
                flex-wrap: wrap;
                align-items: center;
            """,
            "protocols": """
                background-color: #e9ecef;
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
            """,
            "protocol-list": """
                margin-top: 10px;
            """,
            "protocol-item": """
                padding: 8px 0;
                border-bottom: 1px solid #dee2e6;
            """,
            "log": """
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 8px;
                padding: 15px;
                height: 300px;
                overflow-y: auto;
                font-family: 'Courier New', monospace;
                font-size: 13px;
                line-height: 1.4;
            """,
            "info": """
                background-color: #e7f3ff;
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border-left: 4px solid #007bff;
            """,
            "button": """
                padding: 10px 20px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-weight: bold;
                transition: all 0.2s;
            """,
            "button-primary": """
                background-color: #007bff;
                color: white;
            """,
            "button-secondary": """
                background-color: #6c757d;
                color: white;
            """,
            "button-danger": """
                background-color: #dc3545;
                color: white;
            """,
            "button:hover": """
                transform: translateY(-1px);
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            """,
            "button:disabled": """
                background-color: #6c757d;
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            """,
            "input": """
                padding: 10px;
                border: 2px solid #dee2e6;
                border-radius: 6px;
                font-size: 14px;
                flex: 1;
                min-width: 200px;
            """,
            "input:focus": """
                outline: none;
                border-color: #007bff;
                box-shadow: 0 0 0 3px rgba(0,123,255,0.25);
            """,
            "code": """
                background-color: #f8f9fa;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
            """,
        }

    def _generate_css(self, styles: dict[str, str]) -> str:
        """Generate CSS from styles dictionary."""
        css = ""
        for selector, properties in styles.items():
            css += f"{selector} {{{properties}}}\n"
        return css

    def _generate_javascript(self) -> str:
        """Generate JavaScript for browser integration."""
        return f"""
        let ws = null;
        let isConnected = false;
        let messageCount = 0;

        function log(message, type = 'info') {{
            const logDiv = document.getElementById('log');
            const timestamp = new Date().toLocaleTimeString();
            const messageId = ++messageCount;

            const icon = {{
                'info': 'ℹ️',
                'success': '✅',
                'error': '❌',
                'warning': '⚠️',
                'send': '📤',
                'receive': '📥'
            }}[type] || 'ℹ️';

            const logEntry = document.createElement('div');
            logEntry.innerHTML = `[${{timestamp}}] ${{icon}} ${{message}}`;
            logEntry.style.marginBottom = '5px';
            logEntry.style.padding = '2px 0';

            if (type === 'error') {{
                logEntry.style.color = '#dc3545';
                logEntry.style.fontWeight = 'bold';
            }} else if (type === 'success') {{
                logEntry.style.color = '#28a745';
            }} else if (type === 'warning') {{
                logEntry.style.color = '#ffc107';
            }}

            logDiv.appendChild(logEntry);
            logDiv.scrollTop = logDiv.scrollHeight;
        }}

        function updateStatus(status, className) {{
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = status;
            statusDiv.className = `status ${{className}}`;
        }}

        function updateButtons(connected) {{
            document.getElementById('connectBtn').disabled = connected;
            document.getElementById('disconnectBtn').disabled = !connected;
            document.getElementById('messageInput').disabled = !connected;
            document.getElementById('sendBtn').disabled = !connected;
            document.getElementById('chatBtn').disabled = !connected;
        }}

        function connect() {{
            if (isConnected) return;

            updateStatus('Connecting...', 'connecting');
            updateButtons(false);
            log('Attempting to connect to AutoTLS WSS server...', 'info');

            // Connect to WSS with AutoTLS
            const wsUrl = 'wss://localhost:{self.port}/';

            try {{
                ws = new WebSocket(wsUrl);

                ws.onopen = function(event) {{
                    isConnected = true;
                    updateStatus('Connected', 'connected');
                    updateButtons(true);
                    log('Connected to AutoTLS WSS server!', 'success');
                    log('TLS certificate automatically managed', 'info');
                    log('Ready to send messages', 'info');
                }};

                ws.onmessage = function(event) {{
                    log(`Received: ${{event.data}}`, 'receive');
                }};

                ws.onclose = function(event) {{
                    isConnected = false;
                    updateStatus('Disconnected', 'disconnected');
                    updateButtons(false);
                    log('Connection closed', 'warning');
                }};

                ws.onerror = function(error) {{
                    log(`WebSocket error: ${{error}}`, 'error');
                    updateStatus('Error', 'disconnected');
                    updateButtons(false);
                }};

            }} catch (error) {{
                log(`Failed to create WebSocket: ${{error}}`, 'error');
                updateStatus('Error', 'disconnected');
                updateButtons(false);
            }}
        }}

        function disconnect() {{
            if (ws && isConnected) {{
                log('Disconnecting...', 'info');
                ws.close();
            }}
        }}

        function sendMessage() {{
            if (!isConnected || !ws) {{
                log('Not connected to server', 'error');
                return;
            }}

            const input = document.getElementById('messageInput');
            const message = input.value.trim();

            if (message) {{
                log(`Sending echo: ${{message}}`, 'send');
                ws.send(message);
                input.value = '';
            }} else {{
                log('Please enter a message', 'warning');
            }}
        }}

        function sendChat() {{
            if (!isConnected || !ws) {{
                log('Not connected to server', 'error');
                return;
            }}

            const input = document.getElementById('messageInput');
            const message = input.value.trim();

            if (message) {{
                log(`Sending chat: ${{message}}`, 'send');
                ws.send(`CHAT:${{message}}`);
                input.value = '';
            }} else {{
                log('Please enter a message', 'warning');
            }}
        }}

        function clearLog() {{
            const logDiv = document.getElementById('log');
            logDiv.innerHTML = '';
            messageCount = 0;
            log('Log cleared', 'info');
        }}

        // Handle Enter key in input
        document.getElementById('messageInput')
            .addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') {{
                sendMessage();
            }}
        }});

        // Auto-connect on page load if enabled
        window.onload = function() {{
            log('AutoTLS Browser Demo loaded', 'info');
            log('AutoTLS automatically manages TLS certificates', 'info');
            log('Ready to connect to Python libp2p server', 'info');

            {"connect();" if self.auto_connect else ""}
        }};

        // Handle page unload
        window.onbeforeunload = function() {{
            if (ws && isConnected) {{
                ws.close();
            }}
        }};
        """

    def save_html_file(
        self,
        peer_id: ID,
        output_path: str = "autotls_demo.html",
        title: str = "AutoTLS Browser Demo",
    ) -> None:
        """
        Save HTML page to file.

        Args:
            peer_id: Peer ID for connection
            output_path: Output file path
            title: Page title

        """
        html_content = self.generate_html_page(peer_id, title)

        output_file = Path(output_path)
        output_file.write_text(html_content, encoding="utf-8")

        logger.info(f"HTML page saved to {output_file.absolute()}")

    def generate_connection_info(
        self,
        peer_id: ID,
        include_instructions: bool = True,
    ) -> str:
        """
        Generate connection information text.

        Args:
            peer_id: Peer ID for connection
            include_instructions: Whether to include setup instructions

        Returns:
            Connection information text

        """
        info = f"""
AutoTLS Browser Integration Demo
================================

Peer ID: {peer_id}
Domain: {self.domain}
Port: {self.port}

WebSocket URLs:
  WS:  ws://localhost:{self.port}/
  WSS: wss://localhost:{self.port}/

"""

        if include_instructions:
            info += """
Setup Instructions:
1. Start the Python server with AutoTLS enabled
2. Open the generated HTML file in a web browser
3. Click "Connect" to establish WSS connection
4. Certificates are automatically managed by AutoTLS
5. Send messages using the input field

Features:
- Automatic TLS certificate generation
- Certificate renewal and lifecycle management
- Browser-compatible WSS connections
- Real-time message exchange
- Protocol support: /echo/1.0.0, /chat/1.0.0

"""

        return info

    async def test_connection(
        self,
        peer_id: ID,
        timeout: float = 10.0,
    ) -> bool:
        """
        Test WebSocket connection.

        Args:
            peer_id: Peer ID for connection
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful

        """
        try:
            import websockets  # type: ignore

            ws_url = f"wss://localhost:{self.port}/"

            async with websockets.connect(ws_url, timeout=timeout) as websocket:
                # Send test message
                test_message = "test_connection"
                await websocket.send(test_message)

                # Wait for response
                response = await websocket.recv()

                logger.info(f"Connection test successful: {response!r}")
                return True

        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def get_connection_urls(self) -> dict[str, str]:
        """Get connection URLs."""
        return {
            "ws": f"ws://localhost:{self.port}/",
            "wss": f"wss://localhost:{self.port}/",
        }

    def get_certificate_info(self) -> dict[str, str]:
        """Get certificate information."""
        return {
            "domain": self.domain,
            "port": str(self.port),
            "protocol": "WSS",
            "tls": "AutoTLS",
        }

#!/usr/bin/env python3
"""
Simple HTTP server to serve the WebSocket client HTML file.
"""

import http.server
import os
from pathlib import Path
import socketserver
import sys


def serve_html_files(port=8000):
    """Serve HTML files on the specified port."""
    # Change to the directory containing HTML files
    html_dir = Path(__file__).parent
    os.chdir(html_dir)

    # Create HTTP server
    handler = http.server.SimpleHTTPRequestHandler

    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"🌐 Serving HTML files on http://localhost:{port}")
        print(f"📁 Directory: {html_dir}")
        print("\n📄 Enhanced WebSocket Client:")
        print(f"   • http://localhost:{port}/client.html")
        print("\n🚀 WebSocket Demo:")
        print("   1. Start the WebSocket server: python server.py")
        print("   2. Open the WebSocket client in your browser")
        print("   3. Connect to ws://localhost:8080")
        print("   4. Test echo and ping protocols")
        print("\nPress Ctrl+C to stop the server")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 Server stopped")


if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("Invalid port number. Using default port 8000.")

    serve_html_files(port)

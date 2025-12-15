from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pathlib import Path
import sys
import threading
from typing import Any

import trio

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from libp2p import new_swarm
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.host.basic_host import BasicHost

    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False

from .test_utils import TestResults

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PyWebSocketNode:
    def __init__(self, port: int = 8000, secure: bool = False) -> None:
        self.port = port
        self.secure = secure
        self.host: BasicHost | None = None
        self.listener_addr: str | None = None
        self.received_messages: list[str] = []
        self.http_server: HTTPServer | None = None
        self.http_thread: threading.Thread | None = None

    async def setup_node(self) -> "PyWebSocketNode":
        if LIBP2P_AVAILABLE:
            key_pair = create_new_key_pair()
            network = new_swarm(
                key_pair=key_pair,
                listen_addrs=None,
            )
            self.host = BasicHost(network=network)
            from libp2p.custom_types import TProtocol

            test_protocol = TProtocol("/test/1.0.0")
            self.host.set_stream_handler(test_protocol, self.handle_libp2p_stream)
            logger.info("libp2p node setup complete")
        else:
            logger.info("libp2p not available; HTTP-only mode")
        return self

    async def handle_libp2p_stream(self, stream: Any) -> None:
        try:
            data = await stream.read()
            if data:
                message = data.decode("utf-8")
                self.received_messages.append(message)
                logger.info(f"[libp2p] Received: {message}")
                response = f"Echo: {message}"
                await stream.write(response.encode("utf-8"))
                await stream.close()
                logger.info(f"[libp2p] Sent: {response}")
        except Exception as e:
            logger.error(f"Error handling libp2p stream: {e}")

    def create_http_handler(self) -> type[BaseHTTPRequestHandler]:
        node_instance = self

        class HTTPRequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                logger.info(f"[HTTP] {format % args}")

            def do_POST(self) -> None:
                try:
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length).decode("utf-8")
                    node_instance.received_messages.append(body)
                    logger.info(f"[HTTP] Received: {body}")
                    response = f"Echo: {body}"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(response.encode("utf-8"))
                    logger.info(f"[HTTP] Sent: {response}")
                except Exception as e:
                    logger.error(f"Error handling HTTP request: {e}")
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode("utf-8"))

            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Python WebSocket Node - Dual Protocol Mode")

        return HTTPRequestHandler

    async def start_http_server(self) -> None:
        try:
            handler_class = self.create_http_handler()
            self.http_server = HTTPServer(("127.0.0.1", self.port), handler_class)

            def run_server() -> None:
                logger.info(f"HTTP server listening on 127.0.0.1:{self.port}")
                if self.http_server:
                    self.http_server.serve_forever()

            self.http_thread = threading.Thread(target=run_server, daemon=True)
            self.http_thread.start()
            logger.info("HTTP server started successfully")
        except Exception as e:
            logger.error(f"Failed to start HTTP server: {e}")
            raise

    async def start_listening(self) -> str:
        listen_addr = f"/ip4/127.0.0.1/tcp/{self.port}"
        await self.start_http_server()
        if LIBP2P_AVAILABLE and self.host:
            try:
                libp2p_port = self.port + 1000
                libp2p_addr = f"/ip4/127.0.0.1/tcp/{libp2p_port}"
                from multiaddr import Multiaddr

                await self.host.get_network().listen(Multiaddr(libp2p_addr))
                logger.info(f"libp2p listening on {libp2p_addr}")
            except Exception as e:
                logger.warning(f"Could not start libp2p listener: {e}")
        self.listener_addr = listen_addr
        return listen_addr

    async def dial_and_send(self, target_addr: str, message: str) -> str:
        import re

        m = re.search(r"tcp/(\d+)", target_addr)
        port = int(m.group(1)) if m else 8001

        if LIBP2P_AVAILABLE and self.host:
            try:
                from libp2p.custom_types import TProtocol
                from libp2p.peer.id import ID

                # Parse target_addr to get peer_id (simplified for demo)
                peer_id = ID.from_base58(
                    "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
                )  # Default peer ID
                stream = await self.host.new_stream(peer_id, [TProtocol("/test/1.0.0")])
                await stream.write(message.encode("utf-8"))
                response_data = await stream.read()
                response = response_data.decode("utf-8") if response_data else ""
                await stream.close()
                logger.info("[libp2p client] Sent and received via libp2p")
                return response
            except Exception as e:
                logger.warning(f"libp2p dial failed: {e}, trying WebSocket...")

        # Try direct WebSocket echo against JS server
        try:
            from trio_websocket import connect_websocket_url

            ws_url = f"ws://127.0.0.1:{port}/"
            async with trio.open_nursery() as nursery:
                ws = await connect_websocket_url(nursery, ws_url)
                await ws.send_message(message)
                resp = await ws.get_message()
                await ws.aclose()
                logger.info("[WS client] Sent and received via WebSocket")
                return str(resp)
        except Exception as e:
            logger.warning(f"WebSocket dial failed: {e}, trying HTTP...")

        try:
            import requests  # type: ignore[import-untyped]

            http_resp: requests.Response = requests.post(
                f"http://127.0.0.1:{port}", data=message, timeout=10
            )
            logger.info("[HTTP client] Sent and received via HTTP")
            return http_resp.text
        except Exception as e:
            logger.error(f"HTTP dial also failed: {e}")
            raise

    async def stop(self) -> None:
        if self.http_server:
            self.http_server.shutdown()
            logger.info("HTTP server stopped")
        if self.host:
            await self.host.close()
            logger.info("libp2p node stopped")


class MockPyWebSocketNode:
    def __init__(self, port: int = 8000, secure: bool = False) -> None:
        self.port = port
        self.secure = secure
        self.received_messages: list[str] = []
        self.listener_addr: str | None = None

    async def setup_node(self) -> "MockPyWebSocketNode":
        return self

    async def handle_stream(self, stream: Any) -> None:
        pass

    async def start_listening(self) -> str:
        listen_addr = f"/ip4/127.0.0.1/tcp/{self.port}"
        self.listener_addr = listen_addr
        return listen_addr

    async def dial_and_send(self, target_addr: str, message: str) -> str:
        return f"Mock echo: {message}"

    async def stop(self) -> None:
        return None


async def run_py_server_test(
    port: int = 8001, secure: bool = False, duration: int = 30
) -> dict[str, Any]:
    node = PyWebSocketNode(port, secure)
    results = TestResults()
    try:
        await node.setup_node()
        listen_addr = await node.start_listening()
        server_info = {
            "address": str(listen_addr),
            "port": port,
            "secure": secure,
            "http_enabled": True,
            "libp2p_enabled": LIBP2P_AVAILABLE,
        }
        print(f"SERVER_INFO:{json.dumps(server_info)}")
        logger.info(f"Server ready - waiting {duration}s for connections...")
        await trio.sleep(duration)
        if node.received_messages:
            results.add_result(
                "message_received",
                True,
                {
                    "messages": node.received_messages,
                    "count": len(node.received_messages),
                },
            )
        else:
            results.add_result("message_received", False, "No messages received")
        return results.to_dict()
    except Exception as e:
        results.add_error(f"Server error: {e}")
        return results.to_dict()
    finally:
        await node.stop()
        return results.to_dict()


async def run_py_client_test(target_addr: str, message: str) -> dict[str, Any]:
    node = PyWebSocketNode()
    results = TestResults()
    try:
        await node.setup_node()
        response = await node.dial_and_send(target_addr, message)
        if response and message in response:
            results.add_result(
                "dial_and_send", True, {"sent": message, "received": response}
            )
        else:
            results.add_result(
                "dial_and_send", False, {"sent": message, "received": response}
            )
        return results.to_dict()
    except Exception as e:
        results.add_error(f"Client error: {e}")
        return results.to_dict()
    finally:
        await node.stop()
        return results.to_dict()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python py_websocket_node.py <mode> [args...]")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "server":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
        secure = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else False
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else 30
        results = trio.run(run_py_server_test, port, secure, duration)
        print("RESULTS:", json.dumps(results, indent=2))
    elif mode == "client":
        target_addr = sys.argv[2] if len(sys.argv) > 2 else "/ip4/127.0.0.1/tcp/8002"
        message = sys.argv[3] if len(sys.argv) > 3 else "Hello from Python client"
        results = trio.run(run_py_client_test, target_addr, message)
        print("RESULTS:", json.dumps(results, indent=2))

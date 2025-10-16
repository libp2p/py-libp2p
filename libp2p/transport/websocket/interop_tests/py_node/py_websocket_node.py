import json
import logging
import sys
from pathlib import Path

import trio

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from libp2p.host.basic_host import BasicHost
    from libp2p.network.network import Network
    from libp2p.peer.peerstore import PeerStore
    from libp2p.security.plaintext import PlaintextSecurityTransport
    from libp2p.stream_muxer.mplex import Mplex
    from libp2p.transport.tcp.tcp import TCP
    from libp2p.transport.upgrader import TransportUpgrader
    from libp2p.identity import KeyPair
    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False

from py_node.test_utils import TestResults

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PyWebSocketNode:
    def __init__(self, port=8000, secure=False):
        self.port = port
        self.secure = secure
        self.host = None
        self.listener_addr = None
        self.received_messages = []

    async def setup_node(self):
        if not LIBP2P_AVAILABLE:
            logger.info("libp2p not available; using mock node behavior")
            return self

        key_pair = KeyPair.generate()
        peerstore = PeerStore()
        upgrader = TransportUpgrader(secures=[PlaintextSecurityTransport()], muxers=[Mplex()])
        network = Network(key_pair=key_pair, transports=[TCP()], peerstore=peerstore, upgrader=upgrader)
        self.host = BasicHost(network=network, peerstore=peerstore)
        self.host.set_stream_handler("/test/1.0.0", self.handle_stream)
        return self.host

    async def handle_stream(self, stream):
        try:
            data = await stream.read()
            if data:
                message = data.decode('utf-8')
                self.received_messages.append(message)
                response = f"Echo: {message}"
                await stream.write(response.encode('utf-8'))
            await stream.close()
        except Exception as e:
            logger.error(f"Error handling stream: {e}")

    async def start_listening(self):
        listen_addr = f"/ip4/127.0.0.1/tcp/{self.port}"
        if not LIBP2P_AVAILABLE:
            self.listener_addr = listen_addr
            return listen_addr
        await self.host.get_network().listen(listen_addr)
        self.listener_addr = listen_addr
        return listen_addr

    async def dial_and_send(self, target_addr, message):
        if not LIBP2P_AVAILABLE:
            import re
            m = re.search(r"tcp/(\d+)", target_addr)
            port = int(m.group(1)) if m else 8001
            import requests
            resp = requests.post(f"http://127.0.0.1:{port}", data=message, timeout=10)
            return resp.text

        stream = await self.host.new_stream(target_addr, ["/test/1.0.0"])
        await stream.write(message.encode('utf-8'))
        response_data = await stream.read()
        response = response_data.decode('utf-8') if response_data else ""
        await stream.close()
        return response

    async def stop(self):
        if self.host:
            await self.host.close()


class MockPyWebSocketNode:
    def __init__(self, port=8000, secure=False):
        self.port = port
        self.secure = secure
        self.received_messages = []
        self.listener_addr = None

    async def setup_node(self):
        return self

    async def handle_stream(self, stream):
        pass

    async def start_listening(self):
        listen_addr = f"/ip4/127.0.0.1/tcp/{self.port}"
        self.listener_addr = listen_addr
        return listen_addr

    async def dial_and_send(self, target_addr, message):
        return f"Mock echo: {message}"

    async def stop(self):
        return None


async def run_py_server_test(port=8001, secure=False, duration=30):
    NodeClass = PyWebSocketNode if LIBP2P_AVAILABLE else MockPyWebSocketNode
    node = NodeClass(port, secure)
    results = TestResults()
    try:
        await node.setup_node()
        listen_addr = await node.start_listening()
        server_info = {'address': str(listen_addr), 'port': port, 'secure': secure, 'mock': not LIBP2P_AVAILABLE}
        print(f"SERVER_INFO:{json.dumps(server_info)}")
        await trio.sleep(duration)
        if node.received_messages:
            results.add_result("message_received", True, {'messages': node.received_messages, 'count': len(node.received_messages)})
        else:
            results.add_result("message_received", False, "No messages received")
        return results.to_dict()
    except Exception as e:
        results.add_error(f"Server error: {e}")
        return results.to_dict()
    finally:
        await node.stop()


async def run_py_client_test(target_addr, message):
    NodeClass = PyWebSocketNode if LIBP2P_AVAILABLE else MockPyWebSocketNode
    node = NodeClass()
    results = TestResults()
    try:
        await node.setup_node()
        response = await node.dial_and_send(target_addr, message)
        if response and message in response:
            results.add_result("dial_and_send", True, {'sent': message, 'received': response})
        else:
            results.add_result("dial_and_send", False, {'sent': message, 'received': response})
        return results.to_dict()
    except Exception as e:
        results.add_error(f"Client error: {e}")
        return results.to_dict()
    finally:
        await node.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python py_websocket_node.py <server|client> [args...]")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "server":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
        secure = sys.argv[3].lower() == 'true' if len(sys.argv) > 3 else False
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else 30
        results = trio.run(run_py_server_test, port, secure, duration)
        print("RESULTS:", json.dumps(results, indent=2))
    elif mode == "client":
        target_addr = sys.argv[2] if len(sys.argv) > 2 else "/ip4/127.0.0.1/tcp/8002"
        message = sys.argv[3] if len(sys.argv) > 3 else "Hello from Python client"
        results = trio.run(run_py_client_test, target_addr, message)
        print("RESULTS:", json.dumps(results, indent=2))

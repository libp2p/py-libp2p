from pathlib import Path
import subprocess

import pytest
import trio

# Ensure we can import from the local directory structure
# This might be needed if tests/ is not in python path, but usually pytest handles it.
# We will use relative imports based on the package structure.
from tests.interop.websocket.py_node.py_websocket_node import PyWebSocketNode
from tests.interop.websocket.py_node.test_utils import TestResults


@pytest.mark.trio
async def test_py_client_js_server():
    """Test Python client connecting to JavaScript server"""
    results = TestResults()
    js_process = None

    try:
        # Path to js_websocket_node.js relative to this test file
        # tests/interop/websocket/js_node/js_websocket_node.js
        js_node_path = Path(__file__).parent / "js_node" / "js_websocket_node.js"

        if not js_node_path.exists():
            pytest.fail(f"JS Node script not found at {js_node_path}")

        print("Starting JavaScript server...")
        js_process = subprocess.Popen(
            ["node", str(js_node_path), "server", "8002", "false", "15000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Give JS server time to start
        await trio.sleep(3)

        print("Setting up Python client...")
        node = PyWebSocketNode()
        await node.setup_node()

        target_addr = "/ip4/127.0.0.1/tcp/8002"
        test_message = "Hello from Python client"

        print(f"Sending message to JS server: {test_message}")

        try:
            response = await node.dial_and_send(target_addr, test_message)

            if response and test_message in response:
                results.add_result(
                    "py_to_js_communication",
                    True,
                    {"sent": test_message, "received": response},
                )
            else:
                results.add_result(
                    "py_to_js_communication",
                    False,
                    {
                        "sent": test_message,
                        "received": response,
                        "error": "Response does not contain original message",
                    },
                )
                pytest.fail(f"Unexpected response: {response}")

        except Exception as e:
            results.add_result(
                "py_to_js_communication",
                False,
                {"error": f"Connection error: {str(e)}"},
            )
            raise e

        await node.stop()

    finally:
        if js_process:
            js_process.terminate()
            try:
                js_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                js_process.kill()

    # Verify results
    assert results.results["py_to_js_communication"]["success"] is True

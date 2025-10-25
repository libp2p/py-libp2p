import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import trio

sys.path.insert(0, str(Path(__file__).parent.parent))

from py_node.py_websocket_node import PyWebSocketNode  # type: ignore
from py_node.test_utils import TestResults  # type: ignore


async def test_py_client_js_server() -> dict[str, Any]:
    """Test Python client connecting to JavaScript server"""
    results = TestResults()
    js_process = None

    try:
        js_node_path = Path(__file__).parent.parent / "js_node" / "js_websocket_node.js"
        js_process = subprocess.Popen(
            ["node", str(js_node_path), "server", "8002", "false", "15000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        print("Starting JavaScript server...")
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
                print("Python to JS test completed successfully")
                print(f"Received: {response}")
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
                print("Python to JS test failed: unexpected response")

        except Exception as e:
            results.add_result(
                "py_to_js_communication",
                False,
                {"error": f"Connection error: {str(e)}"},
            )
            print(f"Python to JS test failed: {e}")

        await node.stop()

    except Exception as e:
        results.add_error(f"Test error: {e}")
        print(f"Test error: {e}")

    finally:
        if js_process:
            js_process.terminate()
            try:
                js_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                js_process.kill()

    return results.to_dict()


if __name__ == "__main__":
    print("=== Python Client to JavaScript Server Test ===")
    results = trio.run(test_py_client_js_server)
    print("\nTest Results:", json.dumps(results, indent=2))

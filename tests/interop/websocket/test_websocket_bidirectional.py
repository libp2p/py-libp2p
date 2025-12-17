from pathlib import Path
import subprocess

import pytest
import trio

from tests.interop.websocket.py_node.py_websocket_node import PyWebSocketNode


@pytest.mark.trio
async def test_bidirectional_communication():
    """Test bidirectional communication between Python and JavaScript nodes"""
    js_process = None

    try:
        js_node_path = Path(__file__).parent / "js_node" / "js_websocket_node.js"

        if not js_node_path.exists():
            pytest.fail(f"JS Node script not found at {js_node_path}")

        print("Starting JavaScript server...")
        js_process = subprocess.Popen(
            ["node", str(js_node_path), "server", "8005", "false", "30000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        await trio.sleep(3)
        print("JavaScript server started on port 8005")

        print("Setting up Python client...")
        py_node = PyWebSocketNode()
        await py_node.setup_node()

        target_addr = "/ip4/127.0.0.1/tcp/8005"
        test_messages = [
            "Message 1 from Python",
            "Message 2 from Python",
            "Message 3 from Python",
            "Message 4 from Python",
        ]

        successful_exchanges = 0

        print(f"\nSending {len(test_messages)} messages to JavaScript server...\n")

        for i, message in enumerate(test_messages, 1):
            try:
                response = await py_node.dial_and_send(target_addr, message)

                if response and message in response:
                    successful_exchanges += 1
                else:
                    print(f"Exchange {i} failed: unexpected response")

                await trio.sleep(0.1)

            except Exception as e:
                print(f"Exchange {i} failed: {e}")

        await py_node.stop()

        assert successful_exchanges == len(test_messages), (
            f"Only {successful_exchanges}/{len(test_messages)} exchanges successful"
        )

    finally:
        if js_process:
            js_process.terminate()
            try:
                js_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                js_process.kill()

from pathlib import Path
import subprocess
import sys
import trio

sys.path.insert(0, str(Path(__file__).parent.parent))

from py_node.py_websocket_node import PyWebSocketNode
from py_node.test_utils import TestResults


async def _bidirectional_communication_async():
    results = TestResults()
    js_process = None
    try:
        js_cwd = Path(__file__).parent.parent / "js_node"
        js_process = subprocess.Popen([
            'node', 'js_websocket_node.js', 'server', '8005', 'false', '20000'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=js_cwd)

        await trio.sleep(3)

        py_node = PyWebSocketNode(port=8006)
        await py_node.setup_node()
        await py_node.start_listening()

        js_target_addr = '/ip4/127.0.0.1/tcp/8005'
        py_to_js_message = 'Hello from Python to JS'

        try:
            py_to_js_response = await py_node.dial_and_send(js_target_addr, py_to_js_message)
            if py_to_js_response and py_to_js_message in py_to_js_response:
                results.add_result('py_to_js_bidirectional', True, {'sent': py_to_js_message, 'received': py_to_js_response})
            else:
                results.add_result('py_to_js_bidirectional', False, {'sent': py_to_js_message, 'received': py_to_js_response})
        except Exception as e:
            results.add_result('py_to_js_bidirectional', False, f"Error: {e}")

        await trio.sleep(5)

        if getattr(py_node, 'received_messages', None):
            results.add_result('js_to_py_bidirectional', True, {'messages_received': py_node.received_messages, 'count': len(py_node.received_messages)})
        else:
            results.add_result('js_to_py_bidirectional', False, "No messages received from JS")

        messages_to_send = ['Message 1', 'Message 2', 'Message 3']
        successful_exchanges = 0
        for i, message in enumerate(messages_to_send):
            try:
                response = await py_node.dial_and_send(js_target_addr, f"{message} (round {i+1})")
                if response and message in response:
                    successful_exchanges += 1
            except Exception as e:
                results.add_error(f"Failed to send message {i+1}: {e}")

        results.add_result('multiple_message_exchange', successful_exchanges == len(messages_to_send), {'total_messages': len(messages_to_send), 'successful_exchanges': successful_exchanges})
        await py_node.stop()

    except Exception as e:
        results.add_error(f"Bidirectional test error: {e}")

    finally:
        if js_process:
            js_process.terminate()
            try:
                js_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                js_process.kill()

    return results.to_dict()


def test_bidirectional_communication():
    results = trio.run(_bidirectional_communication_async)
    assert 'py_to_js_bidirectional' in results['results']
    assert results['results']['py_to_js_bidirectional']['success'] is True
    assert results['results']['multiple_message_exchange']['success'] is True

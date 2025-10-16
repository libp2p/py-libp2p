from pathlib import Path
import subprocess
import sys
import trio

sys.path.insert(0, str(Path(__file__).parent.parent))

from py_node.test_utils import TestResults


async def _py_client_js_server_async():
    results = TestResults()
    js_process = None
    try:
        js_cwd = Path(__file__).parent.parent / "js_node"
        js_process = subprocess.Popen([
            'node', 'js_websocket_node.js', 'server', '8003', 'false', '15000'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=js_cwd)

        await trio.sleep(3)

        import requests

        target_url = 'http://127.0.0.1:8003'
        test_message = 'Hello from Python client'

        try:
            response = requests.post(target_url, data=test_message, timeout=10)
            response_text = response.text
            if response.status_code == 200 and test_message in response_text:
                results.add_result('py_to_js_communication', True, {'sent': test_message, 'received': response_text})
            else:
                results.add_result('py_to_js_communication', False, {'sent': test_message, 'received': response_text, 'status_code': response.status_code})
        except requests.RequestException as e:
            results.add_result('py_to_js_communication', False, f"Request error: {e}")

    except Exception as e:
        results.add_error(f"Test error: {e}")

    finally:
        if js_process:
            js_process.terminate()
            try:
                js_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                js_process.kill()

    return results.to_dict()


def test_py_client_js_server():
    results = trio.run(_py_client_js_server_async)
    assert 'py_to_js_communication' in results['results']
    assert results['results']['py_to_js_communication']['success'] is True

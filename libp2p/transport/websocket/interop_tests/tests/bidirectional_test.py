import sys
import trio
import json
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from py_node.py_websocket_node import PyWebSocketNode
from py_node.test_utils import TestResults


async def test_bidirectional_communication():
    """Test bidirectional communication between Python and JavaScript nodes"""
    results = TestResults()
    js_process = None
    
    try:
        js_node_path = Path(__file__).parent.parent / "js_node" / "js_websocket_node.js"
        print("Starting JavaScript server...")
        js_process = subprocess.Popen(
            ['node', str(js_node_path), 'server', '8005', 'false', '30000'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
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
            "Message 4 from Python"
        ]
        
        successful_exchanges = 0
        
        print(f"\nSending {len(test_messages)} messages to JavaScript server...\n")
        
        for i, message in enumerate(test_messages, 1):
            try:
                response = await py_node.dial_and_send(target_addr, message)
                
                if response and message in response:
                    successful_exchanges += 1
                    print(f"Exchange {i}/{len(test_messages)}: Success")
                else:
                    print(f"Exchange {i}/{len(test_messages)}: Failed - unexpected response")

                await trio.sleep(0.1)
                
            except Exception as e:
                print(f"Exchange {i}/{len(test_messages)}: Failed - {e}")
        
        await py_node.stop()
        
        print(f"\nResults: {successful_exchanges}/{len(test_messages)} successful exchanges")
        
        if successful_exchanges == len(test_messages):
            results.add_result('bidirectional_communication', True, {
                'total_messages': len(test_messages),
                'successful': successful_exchanges
            })
            print(f"Bidirectional test completed successfully")
        else:
            results.add_result('bidirectional_communication', False, {
                'total_messages': len(test_messages),
                'successful': successful_exchanges,
                'failed': len(test_messages) - successful_exchanges
            })
            print(f"Bidirectional test partially successful")
        
    except Exception as e:
        results.add_error(f"Test error: {e}")
        print(f"❌ Test error: {e}")
        
    finally:
        if js_process:
            print("\nStopping JavaScript server...")
            js_process.terminate()
            try:
                js_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                js_process.kill()
    
    return results.to_dict()


if __name__ == "__main__":
    print("=== Bidirectional Communication Test ===")
    results = trio.run(test_bidirectional_communication)
    print("\nTest Results:", json.dumps(results, indent=2))

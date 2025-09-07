import os
import signal
import subprocess

import pytest
from multiaddr import Multiaddr
import trio
from trio.lowlevel import open_process

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.exceptions import SwarmException
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport

PLAINTEXT_PROTOCOL_ID = "/plaintext/2.0.0"


@pytest.mark.trio
async def test_ping_with_js_node():
    js_node_dir = os.path.join(os.path.dirname(__file__), "js_libp2p", "js_node", "src")
    script_name = "./ws_ping_node.mjs"

    # Debug: Check if JS node directory exists
    print(f"JS Node Directory: {js_node_dir}")
    print(f"JS Node Directory exists: {os.path.exists(js_node_dir)}")

    if os.path.exists(js_node_dir):
        print(f"JS Node Directory contents: {os.listdir(js_node_dir)}")
        script_path = os.path.join(js_node_dir, script_name)
        print(f"Script path: {script_path}")
        print(f"Script exists: {os.path.exists(script_path)}")

        if os.path.exists(script_path):
            with open(script_path) as f:
                script_content = f.read()
                print(f"Script content (first 500 chars): {script_content[:500]}...")

    # Debug: Check if npm is available
    try:
        npm_version = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"NPM version: {npm_version.stdout.strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"NPM not available: {e}")

    # Debug: Check if node is available
    try:
        node_version = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"Node version: {node_version.stdout.strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Node not available: {e}")

    try:
        print(f"Running npm install in {js_node_dir}...")
        npm_install_result = subprocess.run(
            ["npm", "install"],
            cwd=js_node_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"NPM install stdout: {npm_install_result.stdout}")
        print(f"NPM install stderr: {npm_install_result.stderr}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"NPM install failed: {e}")
        pytest.fail(f"Failed to run 'npm install': {e}")

    # Launch the JS libp2p node (long-running)
    print(f"Launching JS node: node {script_name} in {js_node_dir}")
    proc = await open_process(
        ["node", script_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=js_node_dir,
    )
    print(f"JS node process started with PID: {proc.pid}")
    assert proc.stdout is not None, "stdout pipe missing"
    assert proc.stderr is not None, "stderr pipe missing"
    stdout = proc.stdout
    stderr = proc.stderr

    try:
        # Read first two lines (PeerID and multiaddr)
        print("Waiting for JS node to output PeerID and multiaddr...")
        buffer = b""
        with trio.fail_after(30):
            while buffer.count(b"\n") < 2:
                chunk = await stdout.receive_some(1024)
                if not chunk:
                    print("No more data from JS node stdout")
                    break
                buffer += chunk
                print(f"Received chunk: {chunk}")

        print(f"Total buffer received: {buffer}")
        lines = [line for line in buffer.decode().splitlines() if line.strip()]
        print(f"Parsed lines: {lines}")

        if len(lines) < 2:
            print("Not enough lines from JS node, checking stderr...")
            stderr_output = await stderr.receive_some(2048)
            stderr_output = stderr_output.decode()
            print(f"JS node stderr: {stderr_output}")
            pytest.fail(
                "JS node did not produce expected PeerID and multiaddr.\n"
                f"Stdout: {buffer.decode()!r}\n"
                f"Stderr: {stderr_output!r}"
            )
        peer_id_line, addr_line = lines[0], lines[1]
        peer_id = ID.from_base58(peer_id_line)
        maddr = Multiaddr(addr_line)

        # Debug: Print what we're trying to connect to
        print(f"JS Node Peer ID: {peer_id_line}")
        print(f"JS Node Address: {addr_line}")
        print(f"All JS Node lines: {lines}")
        print(f"Parsed multiaddr: {maddr}")

        # Set up Python host
        print("Setting up Python host...")
        key_pair = create_new_key_pair()
        py_peer_id = ID.from_pubkey(key_pair.public_key)
        peer_store = PeerStore()
        peer_store.add_key_pair(py_peer_id, key_pair)
        print(f"Python Peer ID: {py_peer_id}")

        # Use only plaintext security to match the JavaScript node
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )
        transport = WebsocketTransport(upgrader)
        print(f"WebSocket transport created: {transport}")
        swarm = Swarm(py_peer_id, peer_store, upgrader, transport)
        host = BasicHost(swarm)
        print(f"Python host created: {host}")

        # Connect to JS node
        peer_info = PeerInfo(peer_id, [maddr])
        print(f"Python trying to connect to: {peer_info}")
        print(f"Peer info addresses: {peer_info.addrs}")

        # Test WebSocket multiaddr validation
        from libp2p.transport.websocket.multiaddr_utils import (
            is_valid_websocket_multiaddr,
            parse_websocket_multiaddr,
        )

        print(f"Is valid WebSocket multiaddr: {is_valid_websocket_multiaddr(maddr)}")
        try:
            parsed = parse_websocket_multiaddr(maddr)
            print(
                f"Parsed WebSocket multiaddr: is_wss={parsed.is_wss}, sni={parsed.sni}, rest_multiaddr={parsed.rest_multiaddr}"
            )
        except Exception as e:
            print(f"Failed to parse WebSocket multiaddr: {e}")

        await trio.sleep(1)

        try:
            print("Attempting to connect to JS node...")
            await host.connect(peer_info)
            print("Successfully connected to JS node!")
        except SwarmException as e:
            underlying_error = e.__cause__
            print(f"Connection failed with SwarmException: {e}")
            print(f"Underlying error: {underlying_error}")
            pytest.fail(
                "Connection failed with SwarmException.\n"
                f"THE REAL ERROR IS: {underlying_error!r}\n"
            )

        assert host.get_network().connections.get(peer_id) is not None

        # Ping protocol
        stream = await host.new_stream(peer_id, [TProtocol("/ipfs/ping/1.0.0")])
        await stream.write(b"ping")
        data = await stream.read(4)
        assert data == b"pong"

        print("Closing Python host...")
        await host.close()
        print("Python host closed successfully")
    finally:
        print(f"Terminating JS node process (PID: {proc.pid})...")
        try:
            proc.send_signal(signal.SIGTERM)
            print("SIGTERM sent to JS node process")
            await trio.sleep(1)  # Give it time to terminate gracefully
            if proc.poll() is None:
                print("JS node process still running, sending SIGKILL...")
                proc.send_signal(signal.SIGKILL)
                await trio.sleep(0.5)
        except Exception as e:
            print(f"Error terminating JS node process: {e}")

        # Check if process is still running
        if proc.poll() is None:
            print("WARNING: JS node process is still running!")
        else:
            print(f"JS node process terminated with exit code: {proc.poll()}")

        await trio.sleep(0)

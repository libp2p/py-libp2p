import os
import signal
import subprocess

import pytest
from multiaddr import Multiaddr
import trio
from trio.lowlevel import open_process

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.exceptions import SwarmException
from libp2p.peer.id import ID

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
        # Read JS node output until we get peer ID and multiaddrs
        print("Waiting for JS node to output PeerID and multiaddrs...")
        buffer = b""
        peer_id_found: str | bool = False
        multiaddrs_found = []

        with trio.fail_after(30):
            while True:
                chunk = await stdout.receive_some(1024)
                if not chunk:
                    print("No more data from JS node stdout")
                    break
                buffer += chunk
                print(f"Received chunk: {chunk}")

                # Parse lines as we receive them
                lines = buffer.decode().splitlines()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Look for peer ID (starts with "12D3Koo")
                    if line.startswith("12D3Koo") and not peer_id_found:
                        peer_id_found = line
                        print(f"Found peer ID: {peer_id_found}")

                    # Look for multiaddrs (start with "/ip4/" or "/ip6/")
                    elif line.startswith("/ip4/") or line.startswith("/ip6/"):
                        if line not in multiaddrs_found:
                            multiaddrs_found.append(line)
                            print(f"Found multiaddr: {line}")

                # Stop when we have peer ID and at least one multiaddr
                if peer_id_found and multiaddrs_found:
                    print(f"✅ Collected: Peer ID + {len(multiaddrs_found)} multiaddrs")
                    break

        print(f"Total buffer received: {buffer}")
        all_lines = [line for line in buffer.decode().splitlines() if line.strip()]
        print(f"All JS Node lines: {all_lines}")

        if not peer_id_found or not multiaddrs_found:
            print("Missing peer ID or multiaddrs from JS node, checking stderr...")
            stderr_output = await stderr.receive_some(2048)
            stderr_output = stderr_output.decode()
            print(f"JS node stderr: {stderr_output}")
            pytest.fail(
                "JS node did not produce expected PeerID and multiaddr.\n"
                f"Found peer ID: {peer_id_found}\n"
                f"Found multiaddrs: {multiaddrs_found}\n"
                f"Stdout: {buffer.decode()!r}\n"
                f"Stderr: {stderr_output!r}"
            )

        # peer_id = ID.from_base58(peer_id_found)  # Not used currently
        # Use the first localhost multiaddr preferentially, or fallback to first
        # available
        maddr = None
        for addr_str in multiaddrs_found:
            if "127.0.0.1" in addr_str:
                maddr = Multiaddr(addr_str)
                break
        if not maddr:
            maddr = Multiaddr(multiaddrs_found[0])

        # Debug: Print what we're trying to connect to
        print(f"JS Node Peer ID: {peer_id_found}")
        print(f"JS Node Address: {maddr}")
        print(f"All found multiaddrs: {multiaddrs_found}")
        print(f"Selected multiaddr: {maddr}")

        # Set up Python host using new_host API with Noise security
        print("Setting up Python host...")
        from libp2p import create_yamux_muxer_option, new_host

        key_pair = create_new_key_pair()
        # noise_key_pair = create_new_x25519_key_pair()  # Not used currently
        print(f"Python Peer ID: {ID.from_pubkey(key_pair.public_key)}")

        # Use default security options (includes Noise, SecIO, and plaintext)
        # This will allow protocol negotiation to choose the best match
        host = new_host(
            key_pair=key_pair,
            muxer_opt=create_yamux_muxer_option(),
            listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],
        )
        print(f"Python host created: {host}")

        # Connect to JS node using modern peer info
        from libp2p.peer.peerinfo import info_from_p2p_addr

        peer_info = info_from_p2p_addr(maddr)
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
                f"Parsed WebSocket multiaddr: is_wss={parsed.is_wss}, "
                f"sni={parsed.sni}, rest_multiaddr={parsed.rest_multiaddr}"
            )
        except Exception as e:
            print(f"Failed to parse WebSocket multiaddr: {e}")

        # Use proper host.run() context manager
        async with host.run(listen_addrs=[]):
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

            # Verify connection was established
            assert host.get_network().connections.get(peer_info.peer_id) is not None

            # Try to ping the JS node
            ping_protocol = TProtocol("/ipfs/ping/1.0.0")
            try:
                print("Opening ping stream...")
                stream = await host.new_stream(peer_info.peer_id, [ping_protocol])
                print("Ping stream opened successfully!")

                # Send ping data (32 bytes as per libp2p ping protocol)
                ping_data = b"\x00" * 32
                await stream.write(ping_data)
                print(f"Sent ping: {len(ping_data)} bytes")

                # Wait for pong response
                pong_data = await stream.read(32)
                print(f"Received pong: {len(pong_data)} bytes")

                # Verify the pong matches the ping
                assert pong_data == ping_data, (
                    f"Ping/pong mismatch: {ping_data!r} != {pong_data!r}"
                )
                print("✅ Ping/pong successful!")

                await stream.close()
                print("Stream closed successfully!")

            except Exception as e:
                print(f"Ping failed: {e}")
                pytest.fail(f"Ping failed: {e}")

            print("🎉 JavaScript WebSocket interop test completed successfully!")
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

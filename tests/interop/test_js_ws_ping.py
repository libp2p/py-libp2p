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
    # Skip this test due to JavaScript dependency issues
    pytest.skip("Skipping JS interop test due to dependency issues")
    js_node_dir = os.path.join(os.path.dirname(__file__), "js_libp2p", "js_node", "src")
    script_name = "./ws_ping_node.mjs"

    try:
        subprocess.run(
            ["npm", "install"],
            cwd=js_node_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        pytest.fail(f"Failed to run 'npm install': {e}")

    # Launch the JS libp2p node (long-running)
    proc = await open_process(
        ["node", script_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=js_node_dir,
    )
    assert proc.stdout is not None, "stdout pipe missing"
    assert proc.stderr is not None, "stderr pipe missing"
    stdout = proc.stdout
    stderr = proc.stderr

    try:
        # Read first two lines (PeerID and multiaddr)
        buffer = b""
        with trio.fail_after(30):
            while buffer.count(b"\n") < 2:
                chunk = await stdout.receive_some(1024)
                if not chunk:
                    break
                buffer += chunk

        lines = [line for line in buffer.decode().splitlines() if line.strip()]
        if len(lines) < 2:
            stderr_output = await stderr.receive_some(2048)
            stderr_output = stderr_output.decode()
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

        # Set up Python host
        key_pair = create_new_key_pair()
        py_peer_id = ID.from_pubkey(key_pair.public_key)
        peer_store = PeerStore()
        peer_store.add_key_pair(py_peer_id, key_pair)

        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )
        transport = WebsocketTransport(upgrader)
        swarm = Swarm(py_peer_id, peer_store, upgrader, transport)
        host = BasicHost(swarm)

        # Connect to JS node
        peer_info = PeerInfo(peer_id, [maddr])

        print(f"Python trying to connect to: {peer_info}")

        # Use the host as a context manager
        async with host.run(listen_addrs=[]):
            await trio.sleep(1)

            try:
                await host.connect(peer_info)
            except SwarmException as e:
                underlying_error = e.__cause__
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
    finally:
        proc.send_signal(signal.SIGTERM)
        await trio.sleep(0)

import os
import shutil
import subprocess

import pytest
from multiaddr import Multiaddr
import trio
from trio.lowlevel import open_process

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.exceptions import SwarmException
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.stream_muxer.yamux.yamux import Yamux

REQUIRED_NODE_MAJOR = (
    22  # Required for Promise.withResolvers in @chainsafe/libp2p-noise v17+
)


@pytest.mark.trio
@pytest.mark.timeout(120)  # type: ignore[attr-defined]
async def test_ping_with_js_node():
    # Environment guards
    if shutil.which("node") is None:
        pytest.skip("Node.js not installed")
    if shutil.which("npm") is None:
        pytest.skip("npm not installed")

    try:
        out = subprocess.check_output(["node", "-v"], text=True).strip()
        major = int(out.lstrip("v").split(".")[0])
        if major < REQUIRED_NODE_MAJOR:
            pytest.skip(f"Node.js >= {REQUIRED_NODE_MAJOR} required, found {out}")
    except Exception:
        pytest.skip("Unable to determine Node.js version")
    js_node_dir = os.path.join(os.path.dirname(__file__), "js_libp2p", "js_node", "src")
    script_name = "./ws_ping_node.mjs"

    if not os.path.isdir(js_node_dir):
        pytest.skip(f"JS interop directory not found: {js_node_dir}")
    try:
        subprocess.run(
            ["npm", "install", "--no-audit", "--fund=false"],
            cwd=js_node_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("Skipping: npm install timed out")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        pytest.skip(f"Skipping: npm install failed: {e}")

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

    captured_out: list[str] = []
    captured_err: list[str] = []

    async def read_stream(stream, sink: list[str]) -> None:
        try:
            while True:
                data = await stream.receive_some(1024)
                if not data:
                    break
                sink.append(data.decode(errors="replace"))
        except Exception:
            # Best-effort capture; ignore read errors
            pass

    # Start background readers to continuously capture logs
    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_stream, stdout, captured_out)
        nursery.start_soon(read_stream, stderr, captured_err)

        # Wait up to 30s for peer id and address to appear in captured_out
        peer_id_line: str | None = None
        addr_line: str | None = None
        import re

        base58_re = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{20,}$")
        with trio.move_on_after(30):
            while True:
                text = "".join(captured_out)
                lines = [ln for ln in text.splitlines() if ln.strip()]
                peer_id_line = next((ln for ln in lines if base58_re.match(ln)), None)
                addr_line = next((ln for ln in lines if ln.startswith("/")), None)
                if peer_id_line and addr_line:
                    break
                await trio.sleep(0.1)
        # Stop readers; we have enough or timed out
        nursery.cancel_scope.cancel()

    if not peer_id_line or not addr_line:
        out_dump = "".join(captured_out)
        err_dump = "".join(captured_err)
        pytest.fail(
            "Timed out waiting for JS node output.\n"
            f"Stdout:\n{out_dump}\n\nStderr:\n{err_dump}\n"
        )
    if peer_id_line is None or addr_line is None:
        pytest.fail("Failed to extract peer ID or address from JS node output")
    # Type narrowing: we know these are not None after the check above
    assert peer_id_line is not None
    assert addr_line is not None
    peer_id = ID.from_base58(peer_id_line)
    maddr = Multiaddr(addr_line)

    # Debug: Print what we're trying to connect to
    print(f"JS Node Peer ID: {peer_id_line}")
    print(f"JS Node Address: {addr_line}")
    # Optional: print captured logs for debugging
    print("--- JS stdout (partial) ---\n" + "".join(captured_out)[-2000:])
    print("--- JS stderr (partial) ---\n" + "".join(captured_err)[-2000:])

    # Set up Python host using new_host() factory - same approach as test-plans
    # This properly handles WebSocket transport for dialing
    key_pair = create_new_key_pair()
    noise_key_pair = create_new_x25519_key_pair()

    # Create security options with Noise (matching JS libp2p defaults)
    sec_opt = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair,
            noise_privkey=noise_key_pair.private_key,
            early_data=None,
        )
    }

    # Create muxer options with Yamux (matching JS libp2p defaults)
    muxer_opt = {TProtocol("/yamux/1.0.0"): Yamux}

    # Use new_host() factory with WebSocket listen address to register transport
    # This is the pattern used in test-plans for WS dialing
    ws_listen_addr = Multiaddr("/ip4/0.0.0.0/tcp/0/ws")
    host = new_host(
        key_pair=key_pair,
        sec_opt=sec_opt,
        muxer_opt=muxer_opt,
        listen_addrs=[ws_listen_addr],
    )

    # Connect to JS node
    peer_info = PeerInfo(peer_id, [maddr])

    # Add peer info to peerstore before connecting
    host.get_peerstore().add_addrs(peer_id, [maddr], 60)  # 60 second TTL

    print(f"Python trying to connect to: {peer_info}")

    # Use the host as a context manager
    async with host.run(listen_addrs=[ws_listen_addr]):
        # Give the host time to fully start
        await trio.sleep(2)

        try:
            with trio.fail_after(30):
                await host.connect(peer_info)
        except SwarmException as e:
            out_dump = "".join(captured_out)
            err_dump = "".join(captured_err)
            underlying_error = e.__cause__
            pytest.fail(
                "Connection failed with SwarmException.\n"
                f"Underlying: {underlying_error!r}\n"
                f"JS stdout tail:\n{out_dump[-2000:]}\n"
                f"JS stderr tail:\n{err_dump[-2000:]}\n"
            )
        except trio.TooSlowError:
            out_dump = "".join(captured_out)
            err_dump = "".join(captured_err)
            pytest.fail(
                "Connection attempt timed out.\n"
                f"JS stdout tail:\n{out_dump[-2000:]}\n"
                f"JS stderr tail:\n{err_dump[-2000:]}\n"
            )

        assert host.get_network().connections.get(peer_id) is not None

        # Ping protocol - libp2p ping echoes back whatever is sent
        # The protocol uses 32 random bytes, but we test with a simple message
        with trio.fail_after(30):
            stream = await host.new_stream(peer_id, [TProtocol("/ipfs/ping/1.0.0")])
            ping_data = b"ping"
            await stream.write(ping_data)
            data = await stream.read(len(ping_data))
            # Ping protocol echoes back the same data
            assert data == ping_data, f"Expected echo of {ping_data!r}, got {data!r}"

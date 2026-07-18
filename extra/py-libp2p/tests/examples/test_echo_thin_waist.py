import contextlib
import os
from pathlib import Path
import subprocess
import sys
import time

from multiaddr import Multiaddr
from multiaddr.protocols import P_IP4, P_IP6, P_P2P, P_TCP

# pytestmark = pytest.mark.timeout(20)  # Temporarily disabled for debugging

# This test is intentionally lightweight and can be marked as 'integration'.
# It ensures the echo example runs and prints the new Thin Waist lines using
# Trio primitives.

current_file = Path(__file__)
project_root = current_file.parent.parent.parent
EXAMPLES_DIR: Path = project_root / "examples" / "echo"


def test_echo_example_starts_and_prints_thin_waist(monkeypatch, tmp_path):
    """Run echo server and validate printed multiaddr and peer id."""
    # Run echo example as server via module so imports resolve correctly
    cmd = [sys.executable, "-u", "-m", "examples.echo.echo", "-p", "0"]
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc: subprocess.Popen[str] = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=str(project_root),
    )

    if proc.stdout is None:
        proc.terminate()
        raise RuntimeError("Process stdout is None")
    out_stream = proc.stdout

    peer_id: str | None = None
    printed_multiaddr: str | None = None
    saw_waiting = False

    start = time.time()
    timeout_s = 8.0
    try:
        while time.time() - start < timeout_s:
            line = out_stream.readline()
            if not line:
                time.sleep(0.05)
                continue
            s = line.strip()
            if s.startswith("I am "):
                peer_id = s.partition("I am ")[2]
            if s.startswith("echo-demo -d "):
                printed_multiaddr = s.partition("echo-demo -d ")[2]
            if "Waiting for incoming connections..." in s:
                saw_waiting = True
                break
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        with contextlib.suppress(ProcessLookupError):
            proc.kill()

    assert peer_id, "Did not capture peer ID line"
    assert printed_multiaddr, "Did not capture multiaddr line"
    assert saw_waiting, "Did not capture waiting-for-connections line"

    # Validate multiaddr structure using py-multiaddr protocol methods
    ma = Multiaddr(printed_multiaddr)  # should parse without error

    # Check that the multiaddr contains the p2p protocol
    try:
        peer_id_from_multiaddr = ma.value_for_protocol("p2p")
        assert peer_id_from_multiaddr is not None, (
            "Multiaddr missing p2p protocol value"
        )
        assert peer_id_from_multiaddr == peer_id, (
            f"Peer ID mismatch: {peer_id_from_multiaddr} != {peer_id}"
        )
    except Exception as e:
        raise AssertionError(f"Failed to extract p2p protocol value: {e}")

    # Validate the multiaddr structure by checking protocols
    protocols = ma.protocols()

    # Should have at least IP, TCP, and P2P protocols
    assert any(p.code == P_IP4 or p.code == P_IP6 for p in protocols), (
        "Missing IP protocol"
    )
    assert any(p.code == P_TCP for p in protocols), "Missing TCP protocol"
    assert any(p.code == P_P2P for p in protocols), "Missing P2P protocol"

    # Extract the p2p part and validate it matches the captured peer ID
    p2p_part = Multiaddr(f"/p2p/{peer_id}")
    try:
        # Decapsulate the p2p part to get the transport address
        transport_addr = ma.decapsulate(p2p_part)
        # Verify the decapsulated address doesn't contain p2p
        transport_protocols = transport_addr.protocols()
        assert not any(p.code == P_P2P for p in transport_protocols), (
            "Decapsulation failed - still contains p2p"
        )
        # Verify the original multiaddr can be reconstructed
        reconstructed = transport_addr.encapsulate(p2p_part)
        assert str(reconstructed) == str(ma), "Reconstruction failed"
    except Exception as e:
        raise AssertionError(f"Multiaddr decapsulation failed: {e}")

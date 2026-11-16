"""
Shared helpers for the WebRTC-Direct interop tests against other libp2p
implementations (go-libp2p, js-libp2p).

Each harness is a subprocess with the same contract: ``listen`` prints
``LISTEN <multiaddr-with-/p2p/>`` once per address, ``dial -version N <addr>``
prints ``DIAL_OK <peer>`` and exits 0.
"""

from __future__ import annotations

from collections.abc import Sequence
import logging
from pathlib import Path
import subprocess

import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.transport.webrtc.config import WebRTCTransportConfig
from libp2p.transport.webrtc.transport import WebRTCDirectTransport

logger = logging.getLogger(__name__)


def make_transport(**cfg: object) -> WebRTCDirectTransport:
    # ice_servers=[] keeps everything on-box; no public STUN round-trip.
    return WebRTCDirectTransport(
        private_key=create_new_key_pair().private_key,
        config=WebRTCTransportConfig(ice_servers=[], **cfg),  # type: ignore[arg-type]
    )


async def spawn(
    cmd: Sequence[str | Path], *args: str, cwd: Path | None = None
) -> trio.Process:
    return await trio.lowlevel.open_process(
        [*map(str, cmd), *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


async def read_lines(
    proc: trio.Process,
    prefix: str,
    *,
    count: int = 1,
    settle: float = 0.0,
    timeout: float = 45.0,
) -> list[str]:
    """
    Read stdout until at least *count* lines start with *prefix*.

    If *settle* > 0, after the first match keep draining for that many seconds
    so a multi-line burst (e.g. one LISTEN per interface) is collected in one
    call. Without this, a second wait-for-N call either loses siblings already
    sitting in the pipe or burns the full *timeout* when no further lines come.
    """
    stdout = proc.stdout
    assert stdout is not None  # opened with stdout=PIPE above
    found: list[str] = []
    # Mutable cell so the nested drain helper can update the incomplete-line
    # remainder without a `nonlocal` (pyrefly rejects that pattern here).
    buf: list[bytes] = [b""]

    def _consume(chunk: bytes) -> None:
        buf[0] += chunk
        while b"\n" in buf[0]:
            line, buf[0] = buf[0].split(b"\n", 1)
            text = line.decode(errors="replace").strip()
            if text:
                logger.debug("harness: %s", text)
            if text.startswith(prefix):
                found.append(text)

    with trio.move_on_after(timeout):
        while len(found) < count:
            chunk = await stdout.receive_some(4096)
            if not chunk:
                return found
            _consume(chunk)

    if settle > 0.0 and found:
        # Drain siblings from the same burst / near-simultaneous prints.
        with trio.move_on_after(settle):
            while True:
                chunk = await stdout.receive_some(4096)
                if not chunk:
                    break
                _consume(chunk)

    return found


def lan_addr(listen_lines: list[str]) -> str:
    """
    Prefer a concrete non-loopback IPv4 multiaddr (Windows can't reach
    127.0.0.1 from a LAN-bound socket; go gathers LAN host candidates).
    """
    addrs = [ln.split(" ", 1)[1] for ln in listen_lines]
    for a in addrs:
        if a.startswith("/ip4/") and "/ip4/127.0.0.1/" not in a:
            return a
    return addrs[0]

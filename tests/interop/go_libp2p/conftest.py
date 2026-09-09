"""
Fixtures for the go-libp2p WebRTC-Direct and WebTransport interop tests.

Builds small go-libp2p harnesses once (guarded by a file lock so xdist workers
don't race) and skips the whole module when the Go toolchain is unavailable.
"""

import fcntl
import logging
from pathlib import Path
import shutil
import subprocess

import pytest

logger = logging.getLogger(__name__)

_WEBRTC_DIR = Path(__file__).parent / "webrtc_direct"
_WEBRTC_BIN = _WEBRTC_DIR / "go_webrtc_harness"
_WEBRTC_SETUP = Path(__file__).parent / "scripts" / "setup_go_webrtc.sh"

_WT_DIR = Path(__file__).parent / "webtransport"
_WT_BIN = _WT_DIR / "go_webtransport_harness"
_WT_SETUP = Path(__file__).parent / "scripts" / "setup_go_webtransport.sh"


def _go_available() -> bool:
    return shutil.which("go") is not None


def _build_harness(bin_path: Path, setup_script: Path, lock_name: str) -> bool:
    """Build a harness under a lock. Returns True if the binary exists."""
    lock = Path(__file__).parent / lock_name
    with open(lock, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        if bin_path.exists() and bin_path.stat().st_size > 0:
            return True
        try:
            subprocess.run(["bash", str(setup_script)], check=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("go harness build failed: %s", e)
            return False
    return bin_path.exists() and bin_path.stat().st_size > 0


@pytest.fixture(scope="session")
def go_harness() -> Path:
    if not _go_available():
        pytest.skip("go toolchain not available")
    if not _build_harness(_WEBRTC_BIN, _WEBRTC_SETUP, ".setup_lock"):
        pytest.skip("could not build the go-libp2p interop harness")
    return _WEBRTC_BIN


@pytest.fixture(scope="session")
def go_webtransport_harness() -> Path:
    if not _go_available():
        pytest.skip("go toolchain not available")
    if not _build_harness(_WT_BIN, _WT_SETUP, ".setup_wt_lock"):
        pytest.skip("could not build the go-libp2p WebTransport interop harness")
    return _WT_BIN

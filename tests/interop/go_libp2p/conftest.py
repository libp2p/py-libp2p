"""
Fixtures for the go-libp2p WebRTC-Direct interop tests.

Builds a small go-libp2p harness once (guarded by a file lock so xdist workers
don't race) and skips the whole module when the Go toolchain is unavailable.
"""

import fcntl
import logging
from pathlib import Path
import shutil
import subprocess

import pytest

logger = logging.getLogger(__name__)

_HARNESS_DIR = Path(__file__).parent / "webrtc_direct"
_HARNESS_BIN = _HARNESS_DIR / "go_webrtc_harness"
_SETUP = Path(__file__).parent / "scripts" / "setup_go_webrtc.sh"


def _go_available() -> bool:
    return shutil.which("go") is not None


def _build_harness() -> bool:
    """Build the harness under a lock. Returns True if the binary exists."""
    lock = Path(__file__).parent / ".setup_lock"
    with open(lock, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        if _HARNESS_BIN.exists() and _HARNESS_BIN.stat().st_size > 0:
            return True
        try:
            subprocess.run(["bash", str(_SETUP)], check=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("go harness build failed: %s", e)
            return False
    return _HARNESS_BIN.exists() and _HARNESS_BIN.stat().st_size > 0


@pytest.fixture(scope="session")
def go_harness() -> Path:
    if not _go_available():
        pytest.skip("go toolchain not available")
    if not _build_harness():
        pytest.skip("could not build the go-libp2p interop harness")
    return _HARNESS_BIN

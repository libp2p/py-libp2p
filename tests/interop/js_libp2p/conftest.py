"""
Fixtures for the js-libp2p WebRTC-Direct interop tests.

Installs the pinned js-libp2p harness dependencies once (guarded by a file
lock so xdist workers don't race) and skips when Node.js is unavailable.
"""

import logging
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

if sys.platform != "win32":
    import fcntl
else:
    fcntl: Any = None

import pytest

logger = logging.getLogger(__name__)

_WEBRTC_DIR = Path(__file__).parent / "webrtc_direct"


def _install_harness() -> bool:
    """Run ``npm ci`` under a lock. Returns True if the harness is usable."""
    marker = _WEBRTC_DIR / "node_modules" / "@libp2p" / "webrtc" / "package.json"
    lock = Path(__file__).parent / ".setup_webrtc_lock"
    with open(lock, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        if marker.exists():
            return True
        try:
            subprocess.run(
                ["npm", "ci", "--no-audit", "--no-fund"],
                cwd=_WEBRTC_DIR,
                check=True,
                timeout=600,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("js harness install failed: %s", e)
            return False
    return marker.exists()


@pytest.fixture(scope="session")
def js_webrtc_harness() -> tuple[str, Path]:
    """Return ``(node, harness_script)`` for the js-libp2p WebRTC-Direct harness."""
    if sys.platform == "win32":
        pytest.skip("js-libp2p interop tests are not supported on Windows")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not available")
    assert node is not None  # pyrefly doesn't treat pytest.skip() as NoReturn
    if shutil.which("npm") is None:
        pytest.skip("npm not available")
    if not _install_harness():
        pytest.skip("could not install the js-libp2p interop harness")
    return node, _WEBRTC_DIR / "harness.mjs"

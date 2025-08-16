import asyncio
import contextlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

# This test is intentionally lightweight and can be marked as 'integration'.
# It ensures the echo example runs and prints the new Thin Waist lines.

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples" / "echo"


@pytest.mark.timeout(20)
def test_echo_example_starts_and_prints_thin_waist(monkeypatch, tmp_path):
    # We run: python examples/echo/echo.py -p 0
    cmd = [sys.executable, str(EXAMPLES_DIR / "echo.py"), "-p", "0"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None

    found_selected = False
    found_interfaces = False
    start = time.time()

    try:
        while time.time() - start < 10:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            if "Selected binding address:" in line:
                found_selected = True
            if "Available candidate interfaces:" in line:
                found_interfaces = True
            if "Waiting for incoming connections..." in line:
                break
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        with contextlib.suppress(ProcessLookupError):
            proc.kill()

    assert found_selected, "Did not capture Thin Waist binding log line"
    assert found_interfaces, "Did not capture Thin Waist interfaces log line"
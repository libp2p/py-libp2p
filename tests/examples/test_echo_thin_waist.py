import contextlib
import sys
from pathlib import Path

import pytest
import trio

# This test is intentionally lightweight and can be marked as 'integration'.
# It ensures the echo example runs and prints the new Thin Waist lines using Trio primitives.

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples" / "echo"


@pytest.mark.trio
async def test_echo_example_starts_and_prints_thin_waist() -> None:
    cmd = [sys.executable, str(EXAMPLES_DIR / "echo.py"), "-p", "0"]

    found_selected = False
    found_interfaces = False

    # Use a cancellation scope as timeout (similar to previous 10s loop)
    with trio.move_on_after(10) as cancel_scope:
        # Start process streaming stdout
        proc = await trio.open_process(
            cmd,
            stdout=trio.SUBPROCESS_PIPE,
            stderr=trio.STDOUT,
        )

        assert proc.stdout is not None  # for type checkers
        buffer = b""

        try:
            while not (found_selected and found_interfaces):
                # Read some bytes (non-blocking with timeout scope)
                data = await proc.stdout.receive_some(1024)
                if not data:
                    # Process might still be starting; yield control
                    await trio.sleep(0.05)
                    continue
                buffer += data
                # Process complete lines
                *lines, buffer = buffer.split(b"\n") if b"\n" in buffer else ([], buffer)
                for raw in lines:
                    line = raw.decode(errors="ignore")
                    if "Selected binding address:" in line:
                        found_selected = True
                    if "Available candidate interfaces:" in line:
                        found_interfaces = True
                    if "Waiting for incoming connections..." in line:
                        # We have reached steady state; can stop reading further
                        if found_selected and found_interfaces:
                            break
        finally:
            # Terminate the long-running echo example
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                await trio.move_on_after(2)(proc.wait)  # best-effort wait
            if cancel_scope.cancelled_caught:
                # Timeout occurred
                pass

    assert found_selected, "Did not capture Thin Waist binding log line"
    assert found_interfaces, "Did not capture Thin Waist interfaces log line"
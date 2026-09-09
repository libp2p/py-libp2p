import fcntl
import logging
from pathlib import Path
import shutil
import subprocess
import time

import pytest

logger = logging.getLogger(__name__)


def check_nim_available():
    """Check if nim compiler is available."""
    return shutil.which("nim") is not None and shutil.which("nimble") is not None


def check_nim_binary_built():
    """Check if nim echo server binary is built."""
    current_dir = Path(__file__).parent
    binary_path = current_dir / "nim_echo_server"
    return binary_path.exists() and binary_path.stat().st_size > 0


def run_nim_setup_with_lock():
    """Run nim setup with file locking to prevent parallel execution."""
    current_dir = Path(__file__).parent
    lock_file = current_dir / ".setup_lock"
    setup_script = current_dir / "scripts" / "setup_nim_echo.sh"

    if not setup_script.exists():
        raise RuntimeError(f"Setup script not found: {setup_script}")

    # Try to acquire lock
    try:
        with open(lock_file, "w") as f:
            # Non-blocking lock attempt
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Double-check binary doesn't exist (another worker might have built it)
            if check_nim_binary_built():
                logger.info("Binary already exists, skipping setup")
                return

            logger.info("Acquired setup lock, running nim-libp2p setup...")

            # Make setup script executable and run it
            setup_script.chmod(0o755)
            result = subprocess.run(
                [str(setup_script)],
                cwd=current_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Setup failed (exit {result.returncode}):\n"
                    f"stdout: {result.stdout}\n"
                    f"stderr: {result.stderr}"
                )

            # Verify binary was built
            if not check_nim_binary_built():
                raise RuntimeError("nim_echo_server binary not found after setup")

            logger.info("nim-libp2p setup completed successfully")

    except BlockingIOError:
        # Another worker is running setup, wait for it to complete
        logger.info("Another worker is running setup, waiting...")

        # Wait for setup to complete (check every 2 seconds, max 5 minutes)
        for _ in range(150):  # 150 * 2 = 300 seconds = 5 minutes
            if check_nim_binary_built():
                logger.info("Setup completed by another worker")
                return
            time.sleep(2)

        raise TimeoutError("Timed out waiting for setup to complete")

    finally:
        # Clean up lock file
        try:
            lock_file.unlink(missing_ok=True)
        except Exception:
            pass


@pytest.fixture(scope="function")  # Changed to function scope
def nim_echo_binary():
    """Get nim echo server binary path."""
    current_dir = Path(__file__).parent
    binary_path = current_dir / "nim_echo_server"

    if not binary_path.exists():
        pytest.skip(
            "nim_echo_server binary not found. "
            "Run setup script: ./scripts/setup_nim_echo.sh"
        )

    return binary_path


@pytest.fixture
async def nim_server(nim_echo_binary):
    """Start and stop nim echo server for tests."""
    # Import here to avoid circular imports
    # pyrefly: ignore
    from test_echo_interop import NimEchoServer

    server = NimEchoServer(nim_echo_binary)

    try:
        peer_id, listen_addr = await server.start()
        yield server, peer_id, listen_addr
    finally:
        await server.stop()

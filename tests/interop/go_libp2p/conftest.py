import fcntl
import logging
from pathlib import Path
import shutil
import subprocess
import time

import pytest

logger = logging.getLogger(__name__)


def check_go_available():
    """Check if Go compiler is available."""
    return shutil.which("go") is not None


def check_go_binary_built():
    """Check if go echo server binary is built."""
    current_dir = Path(__file__).parent
    binary_path = current_dir / "go_echo_server"
    return binary_path.exists() and binary_path.stat().st_size > 0


def run_go_setup_with_lock():
    """Run go setup with file locking to prevent parallel execution."""
    current_dir = Path(__file__).parent
    lock_file = current_dir / ".setup_lock"
    setup_script = current_dir / "scripts" / "setup_go_echo.sh"

    if not setup_script.exists():
        raise RuntimeError(f"Setup script not found: {setup_script}")

    # Try to acquire lock
    try:
        with open(lock_file, "w") as f:
            # Non-blocking lock attempt
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Double-check binary doesn't exist (another worker might have built it)
            if check_go_binary_built():
                logger.info("Binary already exists, skipping setup")
                return

            logger.info("Acquired setup lock, running go-libp2p setup...")

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
            if not check_go_binary_built():
                raise RuntimeError("go_echo_server binary not found after setup")

            logger.info("go-libp2p setup completed successfully")

    except BlockingIOError:
        # Another worker is running setup, wait for it to complete
        logger.info("Another worker is running setup, waiting...")

        # Wait for setup to complete (check every 2 seconds, max 5 minutes)
        for _ in range(150):  # 150 * 2 = 300 seconds = 5 minutes
            if check_go_binary_built():
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


@pytest.fixture(scope="function")
def go_echo_binary():
    """Get go echo server binary path."""
    current_dir = Path(__file__).parent
    binary_path = current_dir / "go_echo_server"

    if not binary_path.exists():
        pytest.skip(
            "go_echo_server binary not found. "
            "Run setup script: ./scripts/setup_go_echo.sh"
        )

    return binary_path


class GoEchoServer:
    """Go echo server manager for tests."""

    def __init__(self, binary_path: Path):
        self.binary_path = binary_path
        self.process: None | subprocess.Popen = None
        self.peer_id: str | None = None
        self.listen_addr: str | None = None

    async def start(self, timeout: float = 10.0):
        """Start go echo server and get connection info."""
        logger.info(f"Starting go echo server: {self.binary_path}")

        self.process = subprocess.Popen(
            [str(self.binary_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
        )

        # Parse output for connection info
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.process.poll() is not None:
                stdout = self.process.stdout.read() if self.process.stdout else ""
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(
                    f"Server exited early:\nstdout: {stdout}\nstderr: {stderr}"
                )

            if self.process.stdout:
                line = self.process.stdout.readline().strip()
                if not line:
                    continue

                logger.info(f"Server: {line}")

                if line.startswith("Peer ID:"):
                    self.peer_id = line.split(":", 1)[1].strip()

                elif "/quic-v1/p2p/" in line and self.peer_id:
                    # Extract the full multiaddr
                    addr = line.strip()
                    if addr.startswith("/"):
                        self.listen_addr = addr
                        logger.info(f"Server ready: {self.listen_addr}")
                        return self.peer_id, self.listen_addr

        await self.stop()
        raise TimeoutError(f"Server failed to start within {timeout}s")

    async def stop(self):
        """Stop the server."""
        if self.process:
            logger.info("Stopping go echo server...")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None


@pytest.fixture
async def go_server(go_echo_binary):
    """Start and manage go echo server for tests."""
    server = GoEchoServer(go_echo_binary)

    peer_id, listen_addr = await server.start()

    yield server, peer_id, listen_addr

    await server.stop()

import logging
from pathlib import Path
import shutil
import subprocess

import pytest

logger = logging.getLogger(__name__)

RUST_NODE_DIR = Path(__file__).parent / "rust_node"
RUST_BINARY_NAME = "rust_node"


def check_cargo_available():
    """Check if cargo (Rust) is available."""
    return shutil.which("cargo") is not None


def get_rust_binary_path():
    """Get the path to the built rust binary."""
    # Check release build first, then debug
    release_path = RUST_NODE_DIR / "target" / "release" / RUST_BINARY_NAME
    debug_path = RUST_NODE_DIR / "target" / "debug" / RUST_BINARY_NAME

    if release_path.exists():
        return release_path
    if debug_path.exists():
        return debug_path
    return None


def check_rust_binary_built():
    """Check if rust node binary is built."""
    return get_rust_binary_path() is not None


def build_rust_node():
    """Build the rust node binary."""
    if not check_cargo_available():
        raise RuntimeError("cargo not found. Please install Rust: https://rustup.rs/")

    logger.info("Building rust node...")

    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=RUST_NODE_DIR,
        capture_output=True,
        text=True,
        timeout=300,  # 5 minute timeout
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Cargo build failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    if not check_rust_binary_built():
        raise RuntimeError("rust_node binary not found after build")

    logger.info("Rust node built successfully")


@pytest.fixture(scope="session")
def rust_ping_binary():
    """Get rust ping server binary path, building if necessary."""
    # Try to build if not already built
    if not check_rust_binary_built():
        if not check_cargo_available():
            pytest.skip(
                "cargo not found and rust_node binary not pre-built. "
                "Please install Rust (https://rustup.rs/) or build manually: "
                "cd rust_node && cargo build --release"
            )
        build_rust_node()

    binary_path = get_rust_binary_path()
    if binary_path is None:
        pytest.skip("rust_node binary not found")

    return binary_path


@pytest.fixture
async def rust_server(rust_ping_binary):
    """Start and stop rust ping server for tests."""
    # Import here to avoid circular imports
    # pyrefly: ignore
    from test_ping_interop import RustPingServer

    server = RustPingServer(rust_ping_binary)

    try:
        peer_id, listen_addr = await server.start()
        yield server, peer_id, listen_addr
    finally:
        await server.stop()

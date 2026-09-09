import logging
from pathlib import Path
import subprocess
import time

import pytest
import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.host.ping import PingService
from libp2p.peer.peerinfo import info_from_p2p_addr

# configuration
TEST_TIMEOUT = 30
SERVER_START_TIMEOUT = 15.0

# setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RustPingServer:
    """Rust ping server manager."""

    def __init__(self, binary_path: Path):
        self.binary_path = binary_path
        self.process: None | subprocess.Popen = None
        self.peer_id = None
        self.listen_addr = None

    async def start(self):
        """Start rust ping server and get connection info."""
        logger.info(f"starting rust ping Server: {self.binary_path}")

        self.process = subprocess.Popen(
            [str(self.binary_path)],  # type: ignore[missing-attribute]
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )

        # parsing output for connection info
        start_time = time.time()
        while time.time() - start_time < SERVER_START_TIMEOUT:
            if self.process and self.process.poll() and self.process.stdout:
                output = self.process.stdout.read()
                raise RuntimeError(f"Server exited early: {output}")

            reader = self.process.stdout if self.process else None
            if reader:
                line = reader.readline().strip()
                if not line:
                    continue

                logger.info(f"Server: {line}")

                if line.startswith("Local Peer ID:"):
                    self.peer_id = line.split(":", 1)[1].strip()

                elif line.startswith("Listening on:") and self.peer_id:
                    addr_part = line.split(":", 1)[1].strip()
                    if addr_part.startswith("/ip4/") and "/tcp/" in addr_part:
                        self.listen_addr = addr_part
                        logger.info(f"Server ready: {self.listen_addr}")
                        return self.peer_id, self.listen_addr

        await self.stop()
        raise TimeoutError(f"server failed to start within {SERVER_START_TIMEOUT}s")

    async def stop(self):
        """Stop the server."""
        if self.process:
            logger.info("Stopping rust ping server...")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None


async def run_ping_test(server_addr: str, ping_count: int = 5):
    """Test ping protocol against rust server."""
    host = new_host(key_pair=create_new_key_pair())

    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/0")
    rtts = []

    try:
        async with host.run(listen_addrs=[listen_addr]):
            logger.info(f"Local Peer ID: {host.get_id()}")
            logger.info(f"Connecting to rust server: {server_addr}")

            maddr = multiaddr.Multiaddr(server_addr)
            peer_info = info_from_p2p_addr(maddr)
            await host.connect(peer_info)
            logger.info(f"Connected to: {peer_info.peer_id}")

            # creating ping service and sending pings
            ping_service = PingService(host)
            logger.info(f"Sending {ping_count} ping(s)...")

            rtts = await ping_service.ping(peer_info.peer_id, ping_amt=ping_count)

            for i, rtt in enumerate(rtts, 1):
                rtt_ms = rtt / 1000
                logger.info(f"Ping {i}: {rtt_ms:.2f} ms ({rtt} μs)")

            avg_rtt = sum(rtts) / len(rtts) / 1000
            logger.info(f"Average RTT: {avg_rtt:.2f} ms")
            logger.info("Ping test passed!")

    finally:
        await host.close()

    return rtts


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)  # type: ignore[not-callable]
async def test_ping_interop(rust_server):
    """Test basic ping functionality between py-libp2p and rust-libp2p."""
    server, peer_id, listen_addr = rust_server

    logger.info(f"Testing against rust server: {peer_id}")

    with trio.move_on_after(TEST_TIMEOUT - 2):
        rtts = await run_ping_test(listen_addr, ping_count=5)

        # verification of the returned rtts, we got from running the test
        assert len(rtts) == 5, f"Expected 5 RTTs, got {len(rtts)}"
        assert all(rtt > 0 for rtt in rtts), "All RTTs should be positive"

        logger.info("ping interop test passed!")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

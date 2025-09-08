import logging
from pathlib import Path
import subprocess
import time

import pytest
import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.utils.varint import encode_varint_prefixed, read_varint_prefixed_bytes

# Configuration
PROTOCOL_ID = TProtocol("/echo/1.0.0")
TEST_TIMEOUT = 30
SERVER_START_TIMEOUT = 10.0

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NimEchoServer:
    """Simple nim echo server manager."""

    def __init__(self, binary_path: Path):
        self.binary_path = binary_path
        self.process: None | subprocess.Popen = None
        self.peer_id = None
        self.listen_addr = None

    async def start(self):
        """Start nim echo server and get connection info."""
        logger.info(f"Starting nim echo server: {self.binary_path}")

        self.process = subprocess.Popen(
            [str(self.binary_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )

        # Parse output for connection info
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

            if line.startswith("Peer ID:"):
                self.peer_id = line.split(":", 1)[1].strip()

            elif "/quic-v1/p2p/" in line and self.peer_id:
                if line.strip().startswith("/"):
                    self.listen_addr = line.strip()
                    logger.info(f"Server ready: {self.listen_addr}")
                    return self.peer_id, self.listen_addr

        await self.stop()
        raise TimeoutError(f"Server failed to start within {SERVER_START_TIMEOUT}s")

    async def stop(self):
        """Stop the server."""
        if self.process:
            logger.info("Stopping nim echo server...")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None


async def run_echo_test(server_addr: str, messages: list[str]):
    """Test echo protocol against nim server with proper timeout handling."""
    # Create py-libp2p QUIC client with shorter timeouts

    host = new_host(
        enable_quic=True,
        key_pair=create_new_key_pair(),
    )

    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1")
    responses = []

    try:
        async with host.run(listen_addrs=[listen_addr]):
            logger.info(f"Connecting to nim server: {server_addr}")

            # Connect to nim server
            maddr = multiaddr.Multiaddr(server_addr)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)

            # Create stream
            stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
            logger.info("Stream created")

            # Test each message
            for i, message in enumerate(messages, 1):
                logger.info(f"Testing message {i}: {message}")

                # Send with varint length prefix
                data = message.encode("utf-8")
                prefixed_data = encode_varint_prefixed(data)
                await stream.write(prefixed_data)

                # Read response
                response_data = await read_varint_prefixed_bytes(stream)
                response = response_data.decode("utf-8")

                logger.info(f"Got echo: {response}")
                responses.append(response)

                # Verify echo
                assert message == response, (
                    f"Echo failed: sent {message!r}, got {response!r}"
                )

            await stream.close()
            logger.info("✅ All messages echoed correctly")

    finally:
        await host.close()

    return responses


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_basic_echo_interop(nim_server):
    """Test basic echo functionality between py-libp2p and nim-libp2p."""
    server, peer_id, listen_addr = nim_server

    test_messages = [
        "Hello from py-libp2p!",
        "QUIC transport working",
        "Echo test successful!",
        "Unicode: Ñoël, 测试, Ψυχή",
    ]

    logger.info(f"Testing against nim server: {peer_id}")

    # Run test with timeout
    with trio.move_on_after(TEST_TIMEOUT - 2):  # Leave 2s buffer for cleanup
        responses = await run_echo_test(listen_addr, test_messages)

        # Verify all messages echoed correctly
        assert len(responses) == len(test_messages)
        for sent, received in zip(test_messages, responses):
            assert sent == received

        logger.info("✅ Basic echo interop test passed!")


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_large_message_echo(nim_server):
    """Test echo with larger messages."""
    server, peer_id, listen_addr = nim_server

    large_messages = [
        "x" * 1024,
        "y" * 5000,
    ]

    logger.info("Testing large message echo...")

    # Run test with timeout
    with trio.move_on_after(TEST_TIMEOUT - 2):  # Leave 2s buffer for cleanup
        responses = await run_echo_test(listen_addr, large_messages)

        assert len(responses) == len(large_messages)
        for sent, received in zip(large_messages, responses):
            assert sent == received

        logger.info("✅ Large message echo test passed!")


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v", "--tb=short"])

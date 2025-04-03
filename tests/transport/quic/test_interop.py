import subprocess
from typing import (
    Optional,
)

import pytest
import multiaddr

from libp2p.transport.quic.transport import (
    QuicTransport,
)


class ExternalLibp2pNode:
    """Helper class to run external libp2p nodes for interop testing."""

    def __init__(self, implementation: str):
        """
        Initialize external node runner.
        implementation: One of 'go', 'js'
        """
        self.implementation = implementation
        self.process: Optional[subprocess.Popen] = None
        self.multiaddr: Optional[multiaddr.Multiaddr] = None

    async def start(self) -> multiaddr.Multiaddr:
        """Start the external node and return its multiaddr."""
        if self.implementation == "go":
            cmd = ["go", "run", "./cmd/ping/main.go"]
        elif self.implementation == "js":
            cmd = ["node", "./examples/ping/index.js"]
        else:
            raise ValueError(f"Unknown implementation: {self.implementation}")

        # Start process and wait for it to output its multiaddr
        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        # Wait for multiaddr in output
        while True:
            line = self.process.stdout.readline()
            if "Listening on:" in line:
                self.multiaddr = multiaddr.Multiaddr(
                    line.split("Listening on:")[1].strip()
                )
                break

            # Check if process died
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"External node failed to start: {self.process.stderr.read()}"
                )

        return self.multiaddr

    async def stop(self):
        """Stop the external node."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self.multiaddr = None


@pytest.mark.interop
@pytest.mark.asyncio
async def test_quic_go_interop():
    """Test QUIC interoperability with go-libp2p."""
    # Start go-libp2p node
    go_node = ExternalLibp2pNode("go")
    go_addr = await go_node.start()

    try:
        # Create py-libp2p client
        client = QuicTransport()

        # Connect to go node
        protocol, peer_info = await client.dial(go_addr)

        # Test data transfer
        stream = await protocol.open_stream()
        test_data = b"Hello from Python!"

        await stream.write(test_data)
        response = await stream.read()

        assert response == test_data

        await stream.close()
        await client.close()

    finally:
        await go_node.stop()


@pytest.mark.interop
@pytest.mark.asyncio
async def test_quic_js_interop():
    """Test QUIC interoperability with js-libp2p."""
    # Start js-libp2p node
    js_node = ExternalLibp2pNode("js")
    js_addr = await js_node.start()

    try:
        # Create py-libp2p client
        client = QuicTransport()

        # Connect to js node
        protocol, peer_info = await client.dial(js_addr)

        # Test data transfer
        stream = await protocol.open_stream()
        test_data = b"Hello from Python!"

        await stream.write(test_data)
        response = await stream.read()

        assert response == test_data

        await stream.close()
        await client.close()

    finally:
        await js_node.stop()


@pytest.mark.interop
@pytest.mark.asyncio
async def test_quic_py_server_interop():
    """Test other libp2p implementations connecting to py-libp2p QUIC server."""
    # Start py-libp2p server
    server = QuicTransport(host="127.0.0.1", port=0)
    await server.listen()

    multiaddr.Multiaddr(f"/ip4/127.0.0.1/udp/{server.port}/quic")

    # Test with go client
    go_node = ExternalLibp2pNode("go")
    try:
        await go_node.start()
        # Connection test logic here
    finally:
        await go_node.stop()

    # Test with js client
    js_node = ExternalLibp2pNode("js")
    try:
        await js_node.start()
        # Connection test logic here
    finally:
        await js_node.stop()

    await server.close()

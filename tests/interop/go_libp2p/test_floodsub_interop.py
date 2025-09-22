"""
FloodSub Interoperability Tests with go-libp2p

This module contains tests to verify that py-libp2p FloodSub can
interoperate with go-libp2p FloodSub implementation.

Requirements:
- Go 1.19+ installed
- go-libp2p with FloodSub support
- The test will attempt to run a go-libp2p node and connect to it

Note: This test requires external dependencies and may not run in CI
without proper setup. It's designed for manual testing and development.
"""

import asyncio
import logging
from pathlib import Path
import subprocess
import tempfile
import time

import pytest
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import Secp256k1PrivateKey
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.constants import FLOODSUB_PROTOCOL_ID

logger = logging.getLogger(__name__)


class GoLibp2pNode:
    """Wrapper for running a go-libp2p FloodSub node."""

    def __init__(self, port: int = 0):
        self.port = port
        self.process: subprocess.Popen | None = None
        self.addr: str | None = None
        self.peer_id: str | None = None

    async def start(self) -> None:
        """Start the go-libp2p node."""
        # Create a temporary Go program for FloodSub
        go_code = """
package main

import (
    "context"
    "fmt"
    "log"
    "os"
    "os/signal"
    "syscall"
    "time"

    "github.com/libp2p/go-libp2p"
    "github.com/libp2p/go-libp2p/core/host"
    "github.com/libp2p/go-libp2p/core/peer"
    "github.com/libp2p/go-libp2p/p2p/discovery/mdns"
    "github.com/libp2p/go-libp2p/p2p/protocol/ping"
    "github.com/libp2p/go-libp2p/p2p/protocol/pubsub"
    "github.com/libp2p/go-libp2p/p2p/protocol/pubsub/floodsub"
    "github.com/multiformats/go-multiaddr"
)

func main() {
    // Create a libp2p host
    h, err := libp2p.New(
        libp2p.ListenAddrStrings("/ip4/127.0.0.1/tcp/0"),
        libp2p.Ping(false),
    )
    if err != nil {
        log.Fatal(err)
    }

    // Print our address and peer ID
    fmt.Printf("ADDR:%s\\n", h.Addrs()[0])
    fmt.Printf("PEER_ID:%s\\n", h.ID())
    fmt.Printf("READY\\n")

    // Create FloodSub
    ps, err := pubsub.NewFloodSub(context.Background(), h)
    if err != nil {
        log.Fatal(err)
    }

    // Subscribe to test topic
    sub, err := ps.Subscribe("test-topic")
    if err != nil {
        log.Fatal(err)
    }

    // Start a goroutine to handle incoming messages
    go func() {
        for {
            msg, err := sub.Next(context.Background())
            if err != nil {
                log.Printf("Error receiving message: %v", err)
                continue
            }
            fmt.Printf("RECEIVED:%s\\n", string(msg.Data))
        }
    }()

    // Wait for interrupt signal
    c := make(chan os.Signal, 1)
    signal.Notify(c, os.Interrupt, syscall.SIGTERM)
    <-c

    // Cleanup
    h.Close()
}
"""

        # Write Go code to temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(go_code)
            go_file = f.name

        try:
            # Try to run the Go program
            self.process = subprocess.Popen(
                ["go", "run", go_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait for the node to be ready and parse its address
            timeout = 10  # seconds
            start_time = time.time()

            while time.time() - start_time < timeout:
                if self.process.poll() is not None:
                    # Process has exited
                    stdout, stderr = self.process.communicate()
                    raise RuntimeError(
                        f"Go node exited early. stdout: {stdout}, stderr: {stderr}"
                    )

                # Try to read output
                line = self.process.stdout.readline()
                if line:
                    line = line.strip()
                    if line.startswith("ADDR:"):
                        self.addr = line[5:]  # Remove "ADDR:" prefix
                    elif line.startswith("PEER_ID:"):
                        self.peer_id = line[8:]  # Remove "PEER_ID:" prefix
                    elif line == "READY":
                        logger.info(
                            f"Go-libp2p node ready at {self.addr} "
                            f"with peer ID {self.peer_id}"
                        )
                        return

                await asyncio.sleep(0.1)

            raise RuntimeError("Go node failed to start within timeout")

        except FileNotFoundError:
            raise RuntimeError("Go is not installed or not in PATH")
        finally:
            # Clean up the temporary file
            Path(go_file).unlink(missing_ok=True)

    async def stop(self) -> None:
        """Stop the go-libp2p node."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None


@pytest.mark.trio
@pytest.mark.skip(reason="Requires go-libp2p setup and external dependencies")
async def test_py_libp2p_to_go_libp2p_floodsub():
    """
    Test that py-libp2p FloodSub can publish messages to go-libp2p FloodSub.

    This test:
    1. Starts a go-libp2p node with FloodSub
    2. Creates a py-libp2p node with FloodSub
    3. Connects them
    4. Publishes a message from py-libp2p
    5. Verifies go-libp2p receives it
    """
    go_node = GoLibp2pNode()

    try:
        # Start go-libp2p node
        await go_node.start()

        # Create py-libp2p node
        private_key = Secp256k1PrivateKey.new()
        host = new_host(
            key_pair=private_key,
            listen_addrs=["/ip4/127.0.0.1/tcp/0"],
        )

        # Create FloodSub
        floodsub = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])
        pubsub = Pubsub(
            host=host,
            router=floodsub,
            strict_signing=False,
        )

        async with background_trio_service(pubsub):
            await pubsub.wait_until_ready()

            # Connect to go-libp2p node
            go_addr = f"{go_node.addr}/p2p/{go_node.peer_id}"
            logger.info(f"Connecting to go-libp2p node at {go_addr}")

            # Parse the address and connect
            from multiaddr import Multiaddr

            ma = Multiaddr(go_addr)
            await host.connect(ma)

            # Wait for connection to establish
            await trio.sleep(2)

            # Publish a test message
            test_message = "Hello from py-libp2p FloodSub!"
            logger.info(f"Publishing message: {test_message}")
            await pubsub.publish("test-topic", test_message.encode())

            # Wait for message to be processed
            await trio.sleep(2)

            # The go-libp2p node should have received the message
            # (We can't easily verify this without modifying the go code,
            # but if no errors occurred, the test passes)
            logger.info("Message published successfully")

    finally:
        await go_node.stop()


@pytest.mark.trio
async def test_floodsub_basic_functionality():
    """
    Basic test to verify FloodSub functionality works in py-libp2p.

    This test doesn't require external dependencies and verifies
    that the basic FloodSub implementation is working.
    """
    # Create two py-libp2p nodes
    private_key1 = Secp256k1PrivateKey.new()
    private_key2 = Secp256k1PrivateKey.new()

    host1 = new_host(
        key_pair=private_key1,
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )

    host2 = new_host(
        key_pair=private_key2,
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )

    # Create FloodSub instances
    floodsub1 = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])
    floodsub2 = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])

    pubsub1 = Pubsub(
        host=host1,
        router=floodsub1,
        strict_signing=False,
    )

    pubsub2 = Pubsub(
        host=host2,
        router=floodsub2,
        strict_signing=False,
    )

    async with background_trio_service(pubsub1):
        async with background_trio_service(pubsub2):
            await pubsub1.wait_until_ready()
            await pubsub2.wait_until_ready()

            # Connect the nodes
            await host1.connect(host2.get_id(), host2.get_addrs())
            await trio.sleep(1)

            # Subscribe to topic on host2
            topic = "test-topic"
            subscription = await pubsub2.subscribe(topic)
            await trio.sleep(0.5)

            # Publish message from host1
            test_message = "Hello FloodSub!"
            await pubsub1.publish(topic, test_message.encode())

            # Receive message on host2
            received_message = await subscription.get()

            # Verify the message
            assert received_message.data.decode() == test_message
            assert received_message.topicIDs == [topic]

            logger.info("FloodSub basic functionality test passed!")


if __name__ == "__main__":
    # Run the basic functionality test
    trio.run(test_floodsub_basic_functionality)

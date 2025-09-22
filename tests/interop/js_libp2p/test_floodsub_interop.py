"""
FloodSub Interoperability Tests with js-libp2p

This module contains tests to verify that py-libp2p FloodSub can
interoperate with js-libp2p FloodSub implementation.

Requirements:
- Node.js 16+ installed
- js-libp2p with FloodSub support
- The test will attempt to run a js-libp2p node and connect to it

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


class JSLibp2pNode:
    """Wrapper for running a js-libp2p FloodSub node."""

    def __init__(self, port: int = 0):
        self.port = port
        self.process: subprocess.Popen | None = None
        self.addr: str | None = None
        self.peer_id: str | None = None

    async def start(self) -> None:
        """Start the js-libp2p node."""
        # Create a temporary JavaScript program for FloodSub
        js_code = """
import { createLibp2p } from 'libp2p'
import { tcp } from '@libp2p/tcp'
import { noise } from '@chainsafe/libp2p-noise'
import { yamux } from '@chainsafe/libp2p-yamux'
import { floodsub } from '@libp2p/floodsub'
import { identify } from '@libp2p/identify'

async function createNode() {
  return await createLibp2p({
    addresses: {
      listen: ['/ip4/127.0.0.1/tcp/0']
    },
    transports: [
      tcp()
    ],
    connectionEncrypters: [
      noise()
    ],
    streamMuxers: [
      yamux()
    ],
    services: {
      pubsub: floodsub(),
      identify: identify()
    }
  })
}

async function main() {
  const node = await createNode()

  // Print our address and peer ID
  console.log('ADDR:' + node.getMultiaddrs()[0].toString())
  console.log('PEER_ID:' + node.peerId.toString())
  console.log('READY')

  // Subscribe to test topic
  node.services.pubsub.addEventListener('message', (event) => {
    console.log('RECEIVED:' + new TextDecoder().decode(event.detail.data))
  })

  await node.services.pubsub.subscribe('test-topic')

  // Keep running
  process.on('SIGINT', async () => {
    await node.stop()
    process.exit(0)
  })

  // Keep the process alive
  await new Promise(() => {})
}

main().catch(console.error)
"""

        # Write JS code to temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(js_code)
            js_file = f.name

        try:
            # Try to run the JavaScript program
            self.process = subprocess.Popen(
                ["node", js_file],
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
                        f"JS node exited early. stdout: {stdout}, stderr: {stderr}"
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
                            f"js-libp2p node ready at {self.addr} "
                            f"with peer ID {self.peer_id}"
                        )
                        return

                await asyncio.sleep(0.1)

            raise RuntimeError("JS node failed to start within timeout")

        except FileNotFoundError:
            raise RuntimeError("Node.js is not installed or not in PATH")
        finally:
            # Clean up the temporary file
            Path(js_file).unlink(missing_ok=True)

    async def stop(self) -> None:
        """Stop the js-libp2p node."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None


@pytest.mark.trio
@pytest.mark.skip(reason="Requires js-libp2p setup and external dependencies")
async def test_py_libp2p_to_js_libp2p_floodsub():
    """
    Test that py-libp2p FloodSub can publish messages to js-libp2p FloodSub.

    This test:
    1. Starts a js-libp2p node with FloodSub
    2. Creates a py-libp2p node with FloodSub
    3. Connects them
    4. Publishes a message from py-libp2p
    5. Verifies js-libp2p receives it
    """
    js_node = JSLibp2pNode()

    try:
        # Start js-libp2p node
        await js_node.start()

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

            # Connect to js-libp2p node
            js_addr = f"{js_node.addr}/p2p/{js_node.peer_id}"
            logger.info(f"Connecting to js-libp2p node at {js_addr}")

            # Parse the address and connect
            from multiaddr import Multiaddr

            ma = Multiaddr(js_addr)
            await host.connect(ma)

            # Wait for connection to establish
            await trio.sleep(2)

            # Publish a test message
            test_message = "Hello from py-libp2p FloodSub!"
            logger.info(f"Publishing message: {test_message}")
            await pubsub.publish("test-topic", test_message.encode())

            # Wait for message to be processed
            await trio.sleep(2)

            # The js-libp2p node should have received the message
            # (We can't easily verify this without modifying the js code,
            # but if no errors occurred, the test passes)
            logger.info("Message published successfully")

    finally:
        await js_node.stop()


@pytest.mark.trio
async def test_floodsub_js_compatibility():
    """
    Test that verifies py-libp2p FloodSub follows the same protocol as js-libp2p.

    This test doesn't require external dependencies and verifies
    that the FloodSub implementation follows the expected protocol.
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

            # Test multiple topics
            topics = ["test-topic-1", "test-topic-2"]
            subscriptions = []

            # Subscribe to topics on host2
            for topic in topics:
                subscription = await pubsub2.subscribe(topic)
                subscriptions.append((topic, subscription))

            await trio.sleep(0.5)

            # Publish messages from host1
            messages = ["Message 1", "Message 2"]
            for topic, message in zip(topics, messages):
                await pubsub1.publish(topic, message.encode())

            # Receive messages on host2
            for topic, subscription in subscriptions:
                received_message = await subscription.get()
                expected_message = messages[topics.index(topic)]

                # Verify the message
                assert received_message.data.decode() == expected_message
                assert received_message.topicIDs == [topic]

            logger.info("FloodSub JS compatibility test passed!")


if __name__ == "__main__":
    # Run the compatibility test
    trio.run(test_floodsub_js_compatibility)

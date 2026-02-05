#!/usr/bin/env python3
"""
Example script demonstrating WebRTC-Direct (private-to-public) testing in py-libp2p.

This script demonstrates:

1. Setting up a public server node (listening on webrtc-direct)
2. Creating a client peer (simulating browser)
3. Establishing WebRTC-Direct connections
4. Exchanging data over WebRTC streams

Usage:
    python examples/webrtc/test_webrtc_pvt_to_public_example.py
    pytest -n 1 --tb=short tests/core/transport/webrtc -v
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
from typing import Any, cast

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import TProtocol
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.io.abc import ReadWriteCloser
from libp2p.stream_muxer.yamux.yamux import YamuxStream
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)

# Reduce noise from verbose loggers
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("libp2p.transport.webrtc").setLevel(logging.INFO)
logging.getLogger("libp2p.stream_muxer").setLevel(logging.INFO)
logging.getLogger("libp2p.protocol_muxer").setLevel(logging.INFO)
logging.getLogger("libp2p.transport.upgrader").setLevel(logging.INFO)
logging.getLogger("libp2p.transport.webrtc.connection").setLevel(logging.INFO)
logging.getLogger("libp2p.transport.webrtc.private_to_public").setLevel(logging.INFO)

# Default timeout for connection establishment
DEFAULT_CONNECTION_TIMEOUT = 90.0


async def echo_stream_handler(stream: ReadWriteCloser) -> None:
    """Simple echo handler for testing."""
    yamux_stream = cast(YamuxStream, stream)
    try:
        while True:
            data = await yamux_stream.read(1024)
            if not data:
                break
            logger.info(
                f"📨 Echo handler received: {data.decode('utf-8', errors='ignore')}"
            )
            await yamux_stream.write(data)
    except Exception as e:
        logger.debug(f"Echo handler error: {e}")
    finally:
        await yamux_stream.close()


@asynccontextmanager
async def setup_server_peer() -> AsyncGenerator[Any, None]:
    """
    Set up a public server peer that listens on webrtc-direct.

    Yields:
        IHost: Server host configured to listen on webrtc-direct
        WebRTCDirectTransport: The transport instance
        list[Multiaddr]: Listening addresses
        IListener: The listener instance
        trio.Nursery: The transport nursery (must stay alive)

    """
    logger.info("🔧 Setting up Server Peer (Public Node)...")

    # Create server host
    server_host = new_host(
        key_pair=create_new_key_pair(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )
    server_host.set_stream_handler(TProtocol("/echo/1.0.0"), echo_stream_handler)

    # Start the swarm as a service
    swarm = server_host.get_network()
    async with background_trio_service(swarm):
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)  # Allow swarm to start listening

        # Initialize WebRTC-Direct transport
        server_transport = WebRTCDirectTransport()
        server_transport.set_host(server_host)

        # Create nursery for transport background tasks
        # This nursery must stay alive for the entire transport lifetime
        async with trio.open_nursery() as transport_nursery:
            # Start transport with nursery
            await server_transport.start(transport_nursery)
            logger.info("✅ WebRTC-Direct transport started on server")

            # Create listener
            listener = server_transport.create_listener(echo_stream_handler)

            # Start listening on webrtc-direct
            listen_maddr = Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct")
            success = await listener.listen(listen_maddr, transport_nursery)
            assert success, "Server listener failed to start"

            # Get listening addresses
            listen_addrs = listener.get_addrs()
            assert listen_addrs, "Server has no listening addresses"

            logger.info("✅ Server listening on WebRTC-Direct")
            logger.info("📍 Server listening addresses:")
            for addr in listen_addrs:
                logger.info(f"   {addr}")

            # Yield with nursery - nursery must stay alive
            yield (
                server_host,
                server_transport,
                listen_addrs,
                listener,
                transport_nursery,
            )


@asynccontextmanager
async def setup_client_peer() -> AsyncGenerator[Any, None]:
    """
    Set up a client peer (simulating browser) that dials the server.

    Yields:
        IHost: Client host
        WebRTCDirectTransport: The transport instance
        trio.Nursery: The transport nursery (must stay alive)

    """
    logger.info("🔧 Setting up Client Peer (Browser Simulation)...")

    # Create client host
    client_host = new_host(
        key_pair=create_new_key_pair(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Start the swarm as a service
    swarm = client_host.get_network()
    async with background_trio_service(swarm):
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)  # Allow swarm to start listening

        # Initialize WebRTC-Direct transport
        client_transport = WebRTCDirectTransport()
        client_transport.set_host(client_host)

        # Create nursery for transport background tasks
        # This nursery must stay alive for the entire transport lifetime
        async with trio.open_nursery() as transport_nursery:
            # Start transport with nursery
            await client_transport.start(transport_nursery)
            logger.info("✅ WebRTC-Direct transport started on client")

            # Yield with nursery - nursery must stay alive
            yield client_host, client_transport, transport_nursery


async def test_webrtc_direct() -> None:
    """
    Main test function demonstrating WebRTC-Direct connection:
    1. Start server node listening on webrtc-direct
    2. Client dials server using server's multiaddr
    3. Exchange messages over WebRTC connection
    """
    logger.info("=" * 70)
    logger.info("🧪 WebRTC-Direct (Private-to-Public) Connection Test")
    logger.info("=" * 70)
    logger.info("")
    logger.info("This test demonstrates:")
    logger.info("  1. Public server node setup (listening on webrtc-direct)")
    logger.info("  2. Client peer (browser simulation) connecting to server")
    logger.info("  3. WebRTC-Direct connection establishment")
    logger.info("  4. Data exchange over WebRTC streams")
    logger.info("")

    server_transport = None
    client_transport = None
    server_listener = None

    try:
        # Step 1: Set up server peer (public node)
        async with setup_server_peer() as (
            server_host,
            transport,
            listen_addrs,
            listener,
            server_nursery,
        ):
            server_transport = transport
            server_listener = listener

            await trio.sleep(1.0)  # Allow server to fully initialize

            # Step 2: Set up client peer (browser simulation)
            async with setup_client_peer() as (
                client_host,
                client_transport,
                client_nursery,
            ):
                await trio.sleep(1.0)  # Allow client to fully initialize

                # Step 3: Store server address in client's peerstore
                server_id = server_host.get_id()
                server_addr = listen_addrs[0]  # Use first listening address

                # Extract base address (without p2p component) for peerstore
                try:
                    p2p_component = Multiaddr(f"/p2p/{server_id.to_base58()}")
                    base_addr = server_addr.decapsulate(p2p_component)
                except ValueError:
                    base_addr = server_addr

                # Store server address in client's peerstore
                try:
                    client_host.get_peerstore().add_addrs(server_id, [base_addr], 3600)
                    logger.info(
                        "Stored server address for %s in client peerstore",
                        server_id,
                    )
                except Exception as exc:
                    logger.debug(f"Failed to store server address: {exc}")

                # Step 4: Client dials server
                logger.info("")
                logger.info(f"🔌 Client dialing server: {server_addr}")
                logger.info("   (This mimics: browser connecting to public server)")

                # Dial with timeout
                with trio.move_on_after(DEFAULT_CONNECTION_TIMEOUT) as timeout_scope:
                    connection = await client_transport.dial(server_addr)

                if timeout_scope.cancelled_caught:
                    raise TimeoutError(
                        f"Connection timed out after {DEFAULT_CONNECTION_TIMEOUT}s"
                    )

                assert connection is not None, (
                    "Failed to establish WebRTC-Direct connection"
                )
                logger.info("✅ WebRTC-Direct connection established!")
                logger.info("")

                # Step 5: Test data exchange
                logger.info("📤 Testing data exchange over WebRTC-Direct connection...")

                stream = await client_host.new_stream(
                    server_id, [TProtocol("/echo/1.0.0")]
                )

                test_messages = [
                    b"Hello from Client!",
                    b"This is a WebRTC-Direct test message",
                    b"WebRTC-Direct works!",
                ]

                for msg in test_messages:
                    logger.info(f"📤 Sending: {msg.decode('utf-8')}")
                    await stream.write(msg)

                    received = await stream.read(len(msg))
                    exp_s = msg.decode("utf-8", errors="replace")
                    got_s = received.decode("utf-8", errors="replace")
                    assert received == msg, (
                        f"Data mismatch: expected {exp_s!r}, got {got_s!r}"
                    )
                    logger.info("Received echo: %s", received.decode("utf-8"))
                    logger.info("")

                logger.info("🧹 Cleaning up...")
                await stream.close()
                await connection.close()

                logger.info("")
                logger.info("=" * 70)
                logger.info("✅ All tests passed!")
                logger.info("=" * 70)
                logger.info("")
                logger.info("This demonstrates that WebRTC-Direct (private-to-public)")
                logger.info("connections work correctly in py-libp2p.")
                logger.info("")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        raise

    finally:
        logger.info("🧹 Shutting down transports...")
        if server_listener:
            try:
                await server_listener.close()
            except Exception as e:
                logger.debug(f"Error closing server listener: {e}")
        if server_transport:
            try:
                await server_transport.stop()
            except Exception as e:
                logger.debug(f"Error stopping server transport: {e}")
        if client_transport:
            try:
                await client_transport.stop()
            except Exception as e:
                logger.debug(f"Error stopping client transport: {e}")
        logger.info("✅ Cleanup complete")


async def main() -> None:
    """Main entry point."""
    try:
        await test_webrtc_direct()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    trio.run(main)

#!/usr/bin/env python3
"""
Example script demonstrating WebRTC private-to-private testing in py-libp2p.

This script demonstrates:

1. Setting up a Circuit Relay v2 server
2. Creating two NAT peers (simulated)
3. Establishing WebRTC connections through the relay
4. Exchanging data over WebRTC streams

Usage:
    python examples/webrtc/test_webrtc_pvt_to_pvt_example.py
    pytest -n 1 --tb=short tests/core/transport/webrtc -v

"""

import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from contextlib import asynccontextmanager
from typing import cast

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.config import RelayLimits
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID as RELAY_HOP_PROTOCOL_ID,
    STOP_PROTOCOL_ID as RELAY_STOP_PROTOCOL_ID,
    CircuitV2Protocol,
)
from libp2p.stream_muxer.yamux.yamux import YamuxStream
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.tools.utils import connect
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.connection import WebRTCRawConnection
from libp2p.transport.webrtc.private_to_private.transport import WebRTCTransport
from libp2p.transport.webrtc.private_to_private.util import split_addr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)

# Reduce noise from verbose loggers
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("libp2p.transport.webrtc").setLevel(logging.INFO)

# Default relay limits
DEFAULT_RELAY_LIMITS = RelayLimits(
    duration=60 * 60,  # 1 hour
    data=1024 * 1024 * 10,  # 10 MB
    max_circuit_conns=8,
    max_reservations=4,
)


def store_relay_addrs(peer_id: ID, addrs: list[Multiaddr], peerstore) -> None:
    """Normalize relay addresses before storing them in the peerstore."""
    if not addrs:
        return

    suffix = Multiaddr(f"/p2p/{peer_id.to_base58()}")
    normalized: list[Multiaddr] = []

    for addr in addrs:
        base_addr = addr
        try:
            base_addr = addr.decapsulate(suffix)
        except ValueError:
            base_addr = addr
        if str(base_addr) == "":
            continue
        normalized.append(base_addr)

    try:
        peerstore.add_addrs(peer_id, normalized, 3600)
    except Exception as exc:
        logger.debug(f"Failed to store relay addrs for {peer_id}: {exc}")

    # Mark relay protocols in peerstore so relay discovery can find them
    try:
        peerstore.add_protocols(
            peer_id,
            [
                str(RELAY_HOP_PROTOCOL_ID),
                str(RELAY_STOP_PROTOCOL_ID),
            ],
        )
    except Exception as exc:
        logger.debug(f"Failed to mark relay protocols for {peer_id}: {exc}")


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
async def setup_relay_server():
    """
    Set up a Circuit Relay v2 server.

    Yields:
        IHost: Relay host configured as relay server

    """
    logger.info("🔧 Setting up Circuit Relay v2 server...")

    # Create relay host
    relay_host = new_host(
        key_pair=create_new_key_pair(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Start the swarm as a service (required before calling listen())
    # This is what the factories do - swarm must run() before listen() works
    swarm = relay_host.get_network()
    async with background_trio_service(swarm):
        # Now we can call listen() - the event_listener_nursery_created will be set
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)  # Allow swarm to start listening

        # Set up circuit relay protocol as server
        relay_protocol = CircuitV2Protocol(
            relay_host, DEFAULT_RELAY_LIMITS, allow_hop=True
        )

        # Start the relay protocol
        async with background_trio_service(relay_protocol):
            await trio.sleep(0.5)  # Allow protocol to start

            relay_addrs = list(relay_host.get_addrs())
            logger.info(f"✅ Relay server started on: {relay_addrs}")

            if not relay_addrs:
                logger.warning(
                    "⚠️  Relay has no listening addresses - this will cause issues!"
                )

            yield relay_host


@asynccontextmanager
async def setup_nat_peer(relay_host, peer_name: str):
    """
    Set up a NAT peer that connects to the relay (equivalent to browser client).

    Args:
        relay_host: The relay host to connect to
        peer_name: Name for logging (e.g., "Peer A", "Peer B")

    Yields:
        IHost: NAT peer host

    """
    logger.info(f"🔧 Setting up {peer_name}...")

    # Create NAT peer host
    nat_peer = new_host(
        key_pair=create_new_key_pair(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Start the swarm as a service (required before calling listen())
    # The swarm must stay running for the entire lifetime of the host
    swarm = nat_peer.get_network()
    async with background_trio_service(swarm):
        # Now we can call listen() - the event_listener_nursery_created will be set
        await swarm.listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
        await trio.sleep(0.2)  # Allow swarm to start listening

        # Connect to relay
        relay_id = relay_host.get_id()
        relay_addrs = list(relay_host.get_addrs())

        if not relay_addrs:
            logger.warning(f"⚠️  Relay has no addresses, cannot connect {peer_name}")
            yield nat_peer
            return

        # Store relay addresses in peerstore BEFORE connecting
        store_relay_addrs(relay_id, relay_addrs, nat_peer.get_peerstore())
        logger.info(f"📝 Stored relay addresses for {peer_name}: {relay_addrs}")

        try:
            await connect(nat_peer, relay_host)
            await trio.sleep(0.5)  # Allow connection to establish

            # Verify connection
            connected_peers = nat_peer.get_connected_peers()
            if relay_id in connected_peers:
                logger.info(f"✅ {peer_name} connected to relay {relay_id}")
            else:
                logger.warning(
                    f"⚠️  {peer_name} connection to relay not in connected_peers list"
                )
                logger.info(f"   Connected peers: {[str(p) for p in connected_peers]}")
        except Exception as e:
            logger.warning(f"⚠️  Failed to connect {peer_name} to relay: {e}")

        yield nat_peer


async def test_webrtc_private_to_private():
    """
    Main test function demonstrating WebRTC pvt-to-pvt connection:
    1. Start relay server
    2. Connect two browser clients (NAT peers) to relay
    3. Browser A dials Browser B through relay
    4. Exchange messages over WebRTC connection
    """
    logger.info("=" * 70)
    logger.info("🧪 WebRTC Private-to-Private Connection Test")
    logger.info("=" * 70)
    logger.info("")
    logger.info("This test demonstrates:")
    logger.info("  1. Circuit Relay v2 server setup")
    logger.info("  2. Two NAT peers connecting to relay")
    logger.info("  3. WebRTC connection establishment through relay")
    logger.info("  4. Data exchange over WebRTC streams")
    logger.info("")

    transport_a = None
    transport_b = None

    try:
        # Step 1: Set up relay server (equivalent to running relay.js)
        # Use context manager to ensure proper cleanup
        async with setup_relay_server() as relay_host:
            await trio.sleep(1.0)

            # Step 2: Set up two NAT peers (equivalent to two browser windows)
            # Use context managers to ensure swarms stay running
            async with setup_nat_peer(relay_host, "Peer A (Dialer)") as nat_peer_a:
                async with setup_nat_peer(
                    relay_host, "Peer B (Listener)"
                ) as nat_peer_b:
                    # Verify both peers are connected to relay before proceeding
                    relay_id = relay_host.get_id()
                    connected_a = nat_peer_a.get_connected_peers()
                    connected_b = nat_peer_b.get_connected_peers()

                    logger.info(
                        f"📊 Peer A connected peers: {[str(p) for p in connected_a]}"
                    )
                    logger.info(
                        f"📊 Peer B connected peers: {[str(p) for p in connected_b]}"
                    )

                    if relay_id not in connected_a or relay_id not in connected_b:
                        raise RuntimeError(
                            f"Peers not properly connected to relay. "
                            f"Relay ID: {relay_id}, "
                            f"Peer A connected: {relay_id in connected_a}, "
                            f"Peer B connected: {relay_id in connected_b}"
                        )

                    await trio.sleep(1.0)  # Allow connections to stabilize

                    # Step 3: Initialize WebRTC transports
                    # (equivalent to browser clients)
                    logger.info("🔧 Initializing WebRTC transports...")

                    transport_a = WebRTCTransport({})
                    transport_a.set_host(nat_peer_a)
                    await transport_a.start()
                    logger.info("✅ WebRTC transport A started")

                    # Ensure relay is in peerstore for transport A
                    relay_id = relay_host.get_id()
                    relay_addrs = list(relay_host.get_addrs())
                    if relay_addrs:
                        store_relay_addrs(
                            relay_id, relay_addrs, nat_peer_a.get_peerstore()
                        )
                        logger.info(
                            "📝 Stored relay addresses in transport A peerstore"
                        )

                    transport_b = WebRTCTransport({})
                    transport_b.set_host(nat_peer_b)
                    await transport_b.start()
                    logger.info("✅ WebRTC transport B started")

                    # Ensure relay is in peerstore for transport B
                    if relay_addrs:
                        store_relay_addrs(
                            relay_id, relay_addrs, nat_peer_b.get_peerstore()
                        )
                        logger.info(
                            "📝 Stored relay addresses in transport B peerstore"
                        )

                    # Wait a bit for relay discovery to run
                    await trio.sleep(1.0)

                    # Step 4: Start listener on Peer B
                    # (equivalent to browser B listening)
                    logger.info("🔧 Starting WebRTC listener on Peer B...")
                    listener_b = transport_b.create_listener(echo_stream_handler)

                    async with trio.open_nursery() as nursery:
                        success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
                        assert success, "Listener failed to start"
                        logger.info("✅ WebRTC listener started on Peer B")
                        logger.info(" Waiting for relay discovery & addr advertisement")

                        # Manually trigger address refresh to ensure relay addresses
                        # are included
                        transport_b._refresh_listener_addresses()
                        await trio.sleep(2.0)  # Allow time for relay discovery

                        # Step 6: Get advertised addresses
                        # (equivalent to browser showing multiaddrs)
                        webrtc_addrs = listener_b.get_addrs()

                        # If no addresses, try refreshing again
                        if not webrtc_addrs:
                            logger.warning(
                                "⚠️  No addresses after first refresh, trying again..."
                            )
                            # Ensure relay is definitely in peerstore
                            relay_id = relay_host.get_id()
                            relay_addrs = list(relay_host.get_addrs())
                            if relay_addrs:
                                store_relay_addrs(
                                    relay_id, relay_addrs, nat_peer_b.get_peerstore()
                                )
                            transport_b._refresh_listener_addresses()
                            await trio.sleep(1.0)
                            webrtc_addrs = listener_b.get_addrs()

                        assert webrtc_addrs, (
                            "No addresses advertised - "
                            "check relay connection and peerstore"
                        )

                        logger.info("")
                        logger.info("📍 Peer B listening addresses:")
                        for addr in webrtc_addrs:
                            logger.info(f"   {addr}")
                        logger.info("")

                        # Step 7: Prepare peerstore
                        # (equivalent to browser storing relay address)
                        webrtc_addr = webrtc_addrs[0]
                        circuit_addr, target_peer = split_addr(webrtc_addr)
                        target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
                        try:
                            base_addr = circuit_addr.decapsulate(target_component)
                        except ValueError:
                            base_addr = circuit_addr

                        store_relay_addrs(
                            target_peer, [base_addr], nat_peer_a.get_peerstore()
                        )
                        logger.info(
                            f"✅ Stored relay address for {target_peer} "
                            f"in Peer A's peerstore"
                        )

                        # Step 8: Dial through relay
                        # (equivalent to browser A dialing browser B)
                        logger.info("")
                        logger.info(
                            f"🔌 Peer A dialing Peer B through relay: {webrtc_addr}"
                        )
                        logger.info(
                            "   (This mimics: browser A clicking 'Connect' button)"
                        )

                        connection = await transport_a.dial(webrtc_addr)
                        assert connection is not None, (
                            "Failed to establish connection via relay"
                        )
                        logger.info("✅ WebRTC connection established through relay!")
                        logger.info("")

                        # Step 9: Test data exchange
                        # (equivalent to browser sending messages)
                        logger.info(
                            "📤 Testing data exchange over WebRTC connection..."
                        )

                        webrtc_conn = cast(WebRTCRawConnection, connection)
                        stream = await webrtc_conn.open_stream()

                        test_messages = [
                            b"Hello from Peer A!",
                            b"This is a test message",
                            b"WebRTC private-to-private works!",
                        ]

                        for msg in test_messages:
                            logger.info(f"📤 Sending: {msg.decode('utf-8')}")
                            await stream.write(msg)

                            received = await stream.read(len(msg))
                            assert received == msg, (
                                f"Data mismatch: expected {msg}, got {received}"
                            )
                            logger.info(f"📥 Received echo: {received.decode('utf-8')}")
                            logger.info("")

                        logger.info("🧹 Cleaning up...")
                        await stream.close()
                        await connection.close()
                        await listener_b.close()

                        logger.info("")
                        logger.info("=" * 70)
                        logger.info("✅ All tests passed!")
                        logger.info("=" * 70)
                        logger.info("")
                        logger.info("This demonstrates that WebRTC private-to-private")
                        logger.info("connections work correctly in py-libp2p.")
                        logger.info("")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        raise

    finally:
        logger.info("🧹 Shutting down transports and hosts...")
        if transport_a:
            await transport_a.stop()
        if transport_b:
            await transport_b.stop()
        logger.info("✅ Cleanup complete")


async def main():
    """Main entry point."""
    try:
        await test_webrtc_private_to_private()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    trio.run(main)

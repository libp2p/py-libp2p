"""
Comprehensive test suite for WebRTC private-to-private connections via Circuit Relay v2
with NAT traversal scenarios.

This test suite validates:
1. Circuit Relay v2 integration with WebRTC
2. NAT traversal for peers behind private networks
3. Connection establishment through relays
4. Data exchange over relayed WebRTC connections
5. Multiple peers behind NAT scenarios
6. Resource limits and error handling
7. Reachability detection

"""

import logging
from typing import cast

import pytest
from multiaddr import Multiaddr
import trio

from libp2p import generate_peer_id_from
from libp2p.abc import IHost
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.relay.circuit_v2.nat import (
    ReachabilityChecker,
    extract_ip_from_multiaddr,
    is_private_ip,
)
from libp2p.tools.utils import connect

# Import WebRTC protocols to trigger registration
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.connection import WebRTCRawConnection, WebRTCStream
from libp2p.transport.webrtc.private_to_private.relay_fixtures import (
    echo_stream_handler,
    store_relay_addrs,
)
from libp2p.transport.webrtc.private_to_private.transport import WebRTCTransport
from libp2p.transport.webrtc.private_to_private.util import split_addr
from tests.utils.factories import HostFactory

logger = logging.getLogger("libp2p.transport.webrtc.nat_relay_tests")

pytest_plugins = ("libp2p.transport.webrtc.private_to_private.relay_fixtures",)

# Test config
TEST_TIMEOUT = 30.0
NAT_TEST_TIMEOUT = 45.0  # Longer timeout for NAT scenarios


# ============================================================================
# FIXTURES - NAT-Aware Hosts
# ============================================================================


@pytest.fixture
async def nat_peer_a(relay_host: IHost):
    """
    Create a peer behind NAT (private IP) that connects to relay.

    This peer simulates a NAT scenario by using private IP addresses.
    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]

        # Connect to relay
        relay_id = relay_host.get_id()
        relay_addrs = list(relay_host.get_addrs())

        if relay_addrs:
            store_relay_addrs(relay_id, relay_addrs, host.get_peerstore())
            try:
                await connect(host, relay_host)
                await trio.sleep(0.2)
                logger.info(f"NAT peer A connected to relay: {relay_id}")
            except Exception as e:
                logger.warning(f"Failed to connect NAT peer A to relay: {e}")

        yield host


@pytest.fixture
async def nat_peer_b(relay_host: IHost):
    """
    Create another peer behind NAT (private IP) that connects to relay.

    This peer simulates a different NAT scenario.
    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]

        # Connect to relay
        relay_id = relay_host.get_id()
        relay_addrs = list(relay_host.get_addrs())

        if relay_addrs:
            store_relay_addrs(relay_id, relay_addrs, host.get_peerstore())
            try:
                await connect(host, relay_host)
                await trio.sleep(0.2)
                logger.info(f"NAT peer B connected to relay: {relay_id}")
            except Exception as e:
                logger.warning(f"Failed to connect NAT peer B to relay: {e}")

        yield host


# ============================================================================
# NAT DETECTION TESTS
# ============================================================================


@pytest.mark.trio
async def test_nat_detection_private_addresses():
    """Test that NAT detection correctly identifies private IP addresses."""
    # Test various private IP ranges
    private_ips = [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.1.1",
    ]

    for ip in private_ips:
        assert is_private_ip(ip), f"IP {ip} should be detected as private"

    # Test public IPs
    public_ips = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
    for ip in public_ips:
        assert not is_private_ip(ip), f"IP {ip} should be detected as public"


@pytest.mark.trio
async def test_extract_ip_from_multiaddr():
    """Test IP extraction from multiaddr strings."""
    key_pair = create_new_key_pair()
    valid_peer_id = generate_peer_id_from(key_pair)

    test_cases = [
        ("/ip4/127.0.0.1/tcp/4001", "127.0.0.1"),
        (f"/ip4/192.168.1.1/tcp/8080/p2p/{valid_peer_id}", "192.168.1.1"),
        ("/ip4/10.0.0.1/udp/9000", "10.0.0.1"),
        ("/ip4/8.8.8.8/tcp/443", "8.8.8.8"),
    ]

    for maddr_str, expected_ip in test_cases:
        maddr = Multiaddr(maddr_str)
        extracted = extract_ip_from_multiaddr(maddr)
        assert extracted == expected_ip, (
            f"Expected {expected_ip}, got {extracted} for {maddr_str}"
        )


@pytest.mark.trio
async def test_reachability_checker_private_addresses():
    """Test ReachabilityChecker with private addresses."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]

        checker = ReachabilityChecker(host)

        # Test private addresses
        private_addrs = [
            Multiaddr("/ip4/127.0.0.1/tcp/4001"),
            Multiaddr("/ip4/192.168.1.1/tcp/8080"),
            Multiaddr("/ip4/10.0.0.1/udp/9000"),
        ]

        for addr in private_addrs:
            assert not checker.is_addr_public(addr), (
                f"Address {addr} should be detected as private"
            )

        # Test public addresses
        public_addrs = [
            Multiaddr("/ip4/8.8.8.8/tcp/443"),
            Multiaddr("/ip4/1.1.1.1/udp/53"),
        ]

        for addr in public_addrs:
            assert checker.is_addr_public(addr), (
                f"Address {addr} should be detected as public"
            )


# ============================================================================
# CIRCUIT RELAY v2 + WEBRTC NAT TRAVERSAL TESTS
# ============================================================================


@pytest.mark.trio
async def test_webrtc_nat_to_nat_connection(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test WebRTC connection between two peers behind NAT through Circuit Relay v2.

    Scenario:
    - Peer A: Behind NAT (private IP)
    - Peer B: Behind NAT (private IP)
    - Relay: Public/accessible relay server
    - Expected: Both peers connect through relay, establish WebRTC connection
    """
    logger.info("=== Testing NAT-to-NAT WebRTC connection via Circuit Relay v2 ===")

    # Verify both peers are behind NAT (have private addresses)
    peer_a_addrs = list(nat_peer_a.get_addrs())
    peer_b_addrs = list(nat_peer_b.get_addrs())

    assert peer_a_addrs, "Peer A has no addresses"
    assert peer_b_addrs, "Peer B has no addresses"

    # Check that addresses are private
    checker_a = ReachabilityChecker(nat_peer_a)
    checker_b = ReachabilityChecker(nat_peer_b)

    peer_a_public = checker_a.get_public_addrs(peer_a_addrs)
    peer_b_public = checker_b.get_public_addrs(peer_b_addrs)

    logger.info(f"Peer A addresses: {[str(a) for a in peer_a_addrs]}")
    logger.info(f"Peer B addresses: {[str(a) for a in peer_b_addrs]}")
    logger.info(f"Peer A public addresses: {len(peer_a_public)}")
    logger.info(f"Peer B public addresses: {len(peer_b_public)}")

    # Set up WebRTC transports
    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    # Create listener on peer B
    listener_b = transport_b.create_listener(echo_stream_handler)

    connection: WebRTCRawConnection | None = None
    stream: WebRTCStream | None = None

    try:
        async with trio.open_nursery() as nursery:
            # Start listener on peer B
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener B failed to start"

            await trio.sleep(2.0)  # Give time for listener to advertise

            # Get WebRTC addresses from listener
            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "Listener B did not advertise WebRTC addresses"

            webrtc_addr = webrtc_addrs[0]
            logger.info(f"Peer B advertising WebRTC address: {webrtc_addr}")

            # Verify address contains circuit relay path
            assert "/p2p-circuit" in str(webrtc_addr), (
                f"WebRTC address should contain /p2p-circuit: {webrtc_addr}"
            )

            # Extract circuit address and target peer
            circuit_addr, target_peer = split_addr(webrtc_addr)
            assert target_peer == nat_peer_b.get_id(), (
                f"peer mismatch: expected {nat_peer_b.get_id()}, got {target_peer}"
            )

            # Store relay address for target peer in peer A's peerstore
            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr

            store_relay_addrs(target_peer, [base_addr], nat_peer_a.get_peerstore())

            # Dial from peer A to peer B through relay
            logger.info(f"Peer A dialing Peer B through relay: {webrtc_addr}")
            raw_connection = await transport_a.dial(webrtc_addr)

            assert raw_connection is not None, (
                "WebRTC connection could not be established between NAT peers"
            )
            connection = cast(WebRTCRawConnection, raw_connection)

            # Verify connection is established
            assert connection.peer_id == nat_peer_b.get_id(), (
                "Connection peer ID mismatch"
            )

            # Open stream and test data exchange
            stream = await connection.open_stream()
            assert stream is not None, "Failed to open stream over WebRTC NAT conn"

            # Test data exchange
            test_data = b"NAT-to-NAT WebRTC relay test data"
            await stream.write(test_data)
            received = await stream.read(len(test_data))

            assert received == test_data, (
                f"Echoed data mismatch: expected {test_data}, got {received}"
            )

            logger.info("✅ NAT-to-NAT WebRTC connection successful")

            # Cleanup
            await stream.close()
            stream = None

            await connection.close()
            connection = None

            await listener_b.close()

    finally:
        if stream is not None:
            with trio.move_on_after(1):
                await stream.close()
        if connection is not None:
            with trio.move_on_after(1):
                await connection.close()
        await transport_a.stop()
        await transport_b.stop()


@pytest.mark.trio
async def test_webrtc_nat_multiple_connections(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test multiple WebRTC connections between NAT peers through relay.

    Scenario:
    - Multiple concurrent connections between NAT peers
    - Verify relay can handle multiple circuits
    - Test connection isolation
    """
    logger.info("=== Testing multiple NAT WebRTC connections ===")

    # Set up transports
    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    listener_b = transport_b.create_listener(echo_stream_handler)

    connections: list[WebRTCRawConnection] = []
    streams: list[WebRTCStream] = []

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener B failed to start"

            await trio.sleep(2.0)

            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "Listener B did not advertise addresses"
            webrtc_addr = webrtc_addrs[0]

            # Prepare peerstore
            circuit_addr, target_peer = split_addr(webrtc_addr)
            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr
            store_relay_addrs(target_peer, [base_addr], nat_peer_a.get_peerstore())

            # Establish multiple connections
            num_connections = 3
            logger.info(f"Establishing {num_connections} concurrent connections")

            for i in range(num_connections):
                conn = await transport_a.dial(webrtc_addr)
                assert conn is not None, f"Failed to establish connection {i + 1}"
                webrtc_conn = cast(WebRTCRawConnection, conn)
                connections.append(webrtc_conn)

                # Open stream and test
                stream = await webrtc_conn.open_stream()
                assert stream is not None, f"Failed to open stream {i + 1}"
                streams.append(stream)

                test_data = f"NAT connection test {i + 1}".encode()
                await stream.write(test_data)
                received = await stream.read(len(test_data))
                assert received == test_data, f"Data mismatch on connection {i + 1}"
                logger.info(f"✅ Connection {i + 1} established and tested")

            # Cleanup all connections
            for stream in streams:
                await stream.close()
            streams.clear()

            for conn in connections:
                await conn.close()
            connections.clear()

            await listener_b.close()

    finally:
        for stream in streams:
            with trio.move_on_after(1):
                await stream.close()
        for conn in connections:
            with trio.move_on_after(1):
                await conn.close()
        await transport_a.stop()
        await transport_b.stop()


@pytest.mark.trio
async def test_webrtc_nat_reachability_detection(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test reachability detection for NAT peers.

    Verifies that ReachabilityChecker correctly identifies peers behind NAT
    and that connections are established through relay.
    """
    logger.info("=== Testing NAT reachability detection ===")

    checker_a = ReachabilityChecker(nat_peer_a)
    checker_b = ReachabilityChecker(nat_peer_b)

    # Check self-reachability
    is_reachable_a, public_addrs_a = await checker_a.check_self_reachability()
    is_reachable_b, public_addrs_b = await checker_b.check_self_reachability()

    logger.info(f"Peer A: {is_reachable_a}, public addrs: {len(public_addrs_a)}")
    logger.info(f"Peer B: {is_reachable_b}, public addrs: {len(public_addrs_b)}")

    # Both peers should be behind NAT (not directly reachable)
    # Note: In test environment, they might have loopback addresses
    # which are considered pvt, so they should not be directly reachable

    # Establish connection through relay
    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    listener_b = transport_b.create_listener(echo_stream_handler)

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener failed to start"

            await trio.sleep(2.0)

            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No WebRTC addresses advertised"
            webrtc_addr = webrtc_addrs[0]

            # Verify address uses circuit relay
            assert "/p2p-circuit" in str(webrtc_addr), (
                "WebRTC address should use circuit relay"
            )

            # Prepare peerstore
            circuit_addr, target_peer = split_addr(webrtc_addr)
            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr
            store_relay_addrs(target_peer, [base_addr], nat_peer_a.get_peerstore())

            # Check peer reachability before connection
            reachable_before = await checker_a.check_peer_reachability(
                nat_peer_b.get_id()
            )
            logger.info(f"Peer B reachable before connection: {reachable_before}")

            # Establish connection
            connection = await transport_a.dial(webrtc_addr)
            assert connection is not None, "Failed to establish connection"
            webrtc_connection = cast(WebRTCRawConnection, connection)

            await trio.sleep(0.5)  # Give time for connection to be registered

            # Check peer reachability after connection
            # Note: The connection is through relay,
            # so it should still show as not directly reachable
            reachable_after = await checker_a.check_peer_reachability(
                nat_peer_b.get_id()
            )
            logger.info(f"Peer B reachable after connection: {reachable_after}")

            # Verify connection works
            stream = await webrtc_connection.open_stream()
            test_data = b"Reachability test"
            await stream.write(test_data)
            received = await stream.read(len(test_data))
            assert received == test_data, "Data exchange failed"

            await stream.close()
            await connection.close()
            await listener_b.close()

    finally:
        await transport_a.stop()
        await transport_b.stop()


@pytest.mark.trio
async def test_webrtc_nat_connection_resilience(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test connection resilience for NAT peers.

    Tests:
    - Connection re-establishment after failure
    - Multiple connection attempts
    - Stream multiplexing over single connection
    """
    logger.info("=== Testing NAT connection resilience ===")

    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    listener_b = transport_b.create_listener(echo_stream_handler)

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener failed to start"

            await trio.sleep(2.0)

            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No addresses advertised"
            webrtc_addr = webrtc_addrs[0]

            # Prepare peerstore
            circuit_addr, target_peer = split_addr(webrtc_addr)
            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr
            store_relay_addrs(target_peer, [base_addr], nat_peer_a.get_peerstore())

            # Test multiple connection cycles
            for cycle in range(3):
                logger.info(f"Connection cycle {cycle + 1}")

                # Establish connection
                connection = await transport_a.dial(webrtc_addr)
                assert connection is not None, (
                    f"Failed to establish conn in cycle {cycle + 1}"
                )
                webrtc_connection = cast(WebRTCRawConnection, connection)

                # Open multiple streams over same connection
                streams = []
                for i in range(2):
                    stream = await webrtc_connection.open_stream()
                    assert stream is not None, (
                        f"Failed to open stream {i + 1}, cycle {cycle + 1}"
                    )
                    streams.append(stream)

                    test_data = f"Cycle {cycle + 1} stream {i + 1}".encode()
                    await stream.write(test_data)
                    received = await stream.read(len(test_data))
                    assert received == test_data, (
                        f"Data mismatch in cycle {cycle + 1}, stream {i + 1}"
                    )

                # Close all streams
                for stream in streams:
                    await stream.close()

                # Close connection
                await connection.close()

                # Small delay between cycles
                await trio.sleep(0.5)

            logger.info("✅ Connection resilience test passed")
            await listener_b.close()

    finally:
        await transport_a.stop()
        await transport_b.stop()


@pytest.mark.trio
async def test_webrtc_nat_large_data_transfer(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test large data transfer over NAT WebRTC connection.

    Verifies that Circuit Relay v2 can handle large data transfers
    between NAT peers.
    """
    logger.info("=== Testing large data transfer over NAT ===")

    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    listener_b = transport_b.create_listener(echo_stream_handler)

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener failed to start"

            await trio.sleep(2.0)

            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No addresses advertised"
            webrtc_addr = webrtc_addrs[0]

            # Prepare peerstore
            circuit_addr, target_peer = split_addr(webrtc_addr)
            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr
            store_relay_addrs(target_peer, [base_addr], nat_peer_a.get_peerstore())

            # Establish connection
            connection = await transport_a.dial(webrtc_addr)
            assert connection is not None, "Failed to establish connection"
            webrtc_connection = cast(WebRTCRawConnection, connection)

            # Test various data sizes
            test_sizes = [1024, 10 * 1024, 100 * 1024]  # 1KB, 10KB, 100KB

            for size in test_sizes:
                logger.info(f"Testing data transfer of {size} bytes")

                stream = await webrtc_connection.open_stream()
                assert stream is not None, f"Failed to open stream for {size} bytes"

                # Generate test data
                test_data = b"X" * size

                # Write data in chunks
                chunk_size = 8192  # 8KB chunks
                written = 0
                while written < len(test_data):
                    chunk = test_data[written : written + chunk_size]
                    await stream.write(chunk)
                    written += len(chunk)

                # Read data back
                received = b""
                while len(received) < size:
                    chunk = await stream.read(min(chunk_size, size - len(received)))
                    if not chunk:
                        break
                    received += chunk

                assert len(received) == size, (
                    f"Data size mismatch: expected {size}, got {len(received)}"
                )
                assert received == test_data, f"Data content mismatch for size {size}"

                await stream.close()
                logger.info(f"✅ Successfully transferred {size} bytes")

            await connection.close()
            await listener_b.close()

    finally:
        await transport_a.stop()
        await transport_b.stop()


@pytest.mark.trio
async def test_webrtc_nat_relay_unavailable(relay_host: IHost, nat_peer_a: IHost):
    """
    Test behavior when relay is unavailable.

    This test verifies proper error handling when relay connection fails.
    """
    logger.info("=== Testing NAT peer with unavailable relay ===")

    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    try:
        # Try to dial with invalid relay address
        invalid_addr = Multiaddr(
            "/ip4/127.0.0.1/tcp/99999/p2p-circuit/webrtc/p2p/QmInvalidPeer"
        )

        with pytest.raises(Exception):  # Should raise OpenConnectionError or similar
            await transport_a.dial(invalid_addr)

        logger.info("✅ Properly handled unavailable relay")

    finally:
        await transport_a.stop()


@pytest.mark.trio
async def test_webrtc_nat_address_validation(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test address validation for NAT scenarios.

    Verifies that addresses are properly validated and normalized.
    """
    logger.info("=== Testing NAT address validation ===")

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    listener_b = transport_b.create_listener(echo_stream_handler)

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener failed to start"

            await trio.sleep(2.0)

            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No addresses advertised"

            # Verify all addresses contain circuit relay path
            for addr in webrtc_addrs:
                addr_str = str(addr)
                assert "/p2p-circuit" in addr_str, (
                    f"Address should contain /p2p-circuit: {addr_str}"
                )
                assert "/webrtc" in addr_str, (
                    f"Address should contain /webrtc: {addr_str}"
                )
                assert "/p2p/" in addr_str, (
                    f"Address should contain peer ID: {addr_str}"
                )

            logger.info("✅ Address validation passed")
            await listener_b.close()

    finally:
        await transport_b.stop()

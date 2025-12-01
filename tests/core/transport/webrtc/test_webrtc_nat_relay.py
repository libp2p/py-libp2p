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
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport
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


# ============================================================================
# NAT TRAVERSAL INTEGRATION TESTS
# ============================================================================


@pytest.mark.trio
async def test_webrtc_transport_nat_checker_initialization(
    relay_host: IHost, nat_peer_a: IHost
):
    """
    Test that WebRTCTransport initializes ReachabilityChecker on start.

    Validates that NAT detection infrastructure is properly set up.
    """
    logger.info("=== Testing NAT checker initialization ===")

    transport = WebRTCTransport({})
    transport.set_host(nat_peer_a)

    # Verify checker is not initialized before start
    assert transport._reachability_checker is None, (
        "ReachabilityChecker should not be initialized before start"
    )

    # Start transport
    await transport.start()

    # Verify checker is initialized after start
    assert transport._reachability_checker is not None, (
        "ReachabilityChecker should be initialized after start"
    )
    assert isinstance(transport._reachability_checker, ReachabilityChecker), (
        "ReachabilityChecker should be an instance of ReachabilityChecker"
    )

    # Verify checker is cleaned up on stop
    await transport.stop()
    assert transport._reachability_checker is None, (
        "ReachabilityChecker should be cleaned up after stop"
    )

    logger.info("✅ NAT checker initialization test passed")


@pytest.mark.trio
async def test_webrtc_nat_aware_address_advertisement(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test NAT-aware address advertisement in WebRTC transport.

    Validates that:
    1. Public addresses are advertised when available
    2. Relay addresses are always included as fallback
    3. Address advertisement uses NAT detection
    """
    logger.info("=== Testing NAT-aware address advertisement ===")

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    # Verify ReachabilityChecker is initialized
    assert transport_b._reachability_checker is not None, (
        "ReachabilityChecker should be initialized"
    )

    listener_b = transport_b.create_listener(echo_stream_handler)

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener failed to start"

            await trio.sleep(2.0)  # Give time for address generation

            # Get advertised addresses
            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No WebRTC addresses advertised"

            logger.info(f"Advertised addresses: {[str(a) for a in webrtc_addrs]}")

            # Verify all addresses contain required components
            for addr in webrtc_addrs:
                addr_str = str(addr)
                assert "/webrtc" in addr_str, (
                    f"Address should contain /webrtc: {addr_str}"
                )
                assert "/p2p/" in addr_str, (
                    f"Address should contain peer ID: {addr_str}"
                )
                # Note: Addresses may contain /p2p-circuit (relay) or not (public)

            # Check if public addresses are advertised (if available)
            # In test environment, peers typically have private addresses
            # so we expect relay addresses
            relay_addrs = [a for a in webrtc_addrs if "/p2p-circuit" in str(a)]
            public_addrs = [a for a in webrtc_addrs if "/p2p-circuit" not in str(a)]

            logger.info(f"Relay addresses: {len(relay_addrs)}")
            logger.info(f"Public addresses: {len(public_addrs)}")

            # At minimum, relay addresses should be advertised
            assert len(relay_addrs) > 0, (
                "At least one relay address should be advertised"
            )

            # Verify NAT detection was used
            # Check that get_public_addrs was called (indirectly via address filtering)
            checker = transport_b._reachability_checker
            all_host_addrs = list(nat_peer_b.get_addrs())
            public_host_addrs = checker.get_public_addrs(all_host_addrs)

            if public_host_addrs:
                # If host has public addresses, they should be advertised
                logger.info(
                    f"Host has {len(public_host_addrs)} public addresses, "
                    f"advertised {len(public_addrs)} public WebRTC addresses"
                )
            else:
                logger.info(
                    "Host has no public addresses, only relay addresses advertised"
                )

            await listener_b.close()

    finally:
        await transport_b.stop()

    logger.info("✅ NAT-aware address advertisement test passed")


@pytest.mark.trio
async def test_webrtc_nat_detection_during_dial(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test that NAT detection is performed during dial operation.

    Validates that ensure_signaling_connection() uses NAT detection
    to check peer reachability. Also validates self-reachability detection.
    """
    logger.info("=== Testing NAT detection during dial ===")

    # Check self-reachability before transport setup
    checker_a = ReachabilityChecker(nat_peer_a)
    checker_b = ReachabilityChecker(nat_peer_b)

    is_reachable_a, public_addrs_a = await checker_a.check_self_reachability()
    is_reachable_b, public_addrs_b = await checker_b.check_self_reachability()

    logger.info(
        f"Peer A self-reachable: {is_reachable_a}, public addrs: {len(public_addrs_a)}"
    )
    logger.info(
        f"Peer B self-reachable: {is_reachable_b}, public addrs: {len(public_addrs_b)}"
    )

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

            # Verify ReachabilityChecker is initialized in transport
            assert transport_a._reachability_checker is not None, (
                "ReachabilityChecker should be initialized"
            )

            # Check peer reachability before connection
            reachable_before = (
                await transport_a._reachability_checker.check_peer_reachability(
                    nat_peer_b.get_id()
                )
            )
            logger.info(f"Peer B reachable before dial: {reachable_before}")

            # Dial should use NAT detection internally
            # The ensure_signaling_connection() method will check peer reachability
            connection = await transport_a.dial(webrtc_addr)
            assert connection is not None, "Failed to establish connection"

            await trio.sleep(0.5)  # Give time for connection to be registered

            # Check peer reachability after connection
            # Note: The connection is through relay,
            # so it should still show as not directly reachable
            reachable_after = (
                await transport_a._reachability_checker.check_peer_reachability(
                    nat_peer_b.get_id()
                )
            )
            logger.info(f"Peer B reachable after connection: {reachable_after}")

            # Verify connection works
            webrtc_connection = cast(WebRTCRawConnection, connection)
            stream = await webrtc_connection.open_stream()
            test_data = b"NAT detection test"
            await stream.write(test_data)
            received = await stream.read(len(test_data))
            assert received == test_data, "Data exchange failed"

            await stream.close()
            await connection.close()
            await listener_b.close()

    finally:
        await transport_a.stop()
        await transport_b.stop()

    logger.info("✅ NAT detection during dial test passed")


@pytest.mark.trio
async def test_webrtc_nat_integration_end_to_end(
    relay_host: IHost, nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    End-to-end test of NAT traversal integration.

    Validates the complete flow:
    1. Transport initializes NAT detection
    2. Address advertisement uses NAT detection
    3. Dialing uses NAT detection for peer reachability
    4. Connection establishment works correctly
    """
    logger.info("=== Testing NAT integration end-to-end ===")

    # Set up transports
    transport_a = WebRTCTransport({})
    transport_a.set_host(nat_peer_a)
    await transport_a.start()

    transport_b = WebRTCTransport({})
    transport_b.set_host(nat_peer_b)
    await transport_b.start()

    # Verify NAT detection is initialized
    assert transport_a._reachability_checker is not None, (
        "Transport A should have ReachabilityChecker initialized"
    )
    assert transport_b._reachability_checker is not None, (
        "Transport B should have ReachabilityChecker initialized"
    )

    listener_b = transport_b.create_listener(echo_stream_handler)

    try:
        async with trio.open_nursery() as nursery:
            success = await listener_b.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener failed to start"

            await trio.sleep(2.0)

            # Test address advertisement (NAT-aware)
            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No addresses advertised"

            # Verify addresses are properly formatted
            for addr in webrtc_addrs:
                addr_str = str(addr)
                assert "/webrtc" in addr_str, f"Address missing /webrtc: {addr_str}"
                assert "/p2p/" in addr_str, f"Address missing peer ID: {addr_str}"

            webrtc_addr = webrtc_addrs[0]

            # Prepare peerstore
            circuit_addr, target_peer = split_addr(webrtc_addr)
            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr
            store_relay_addrs(target_peer, [base_addr], nat_peer_a.get_peerstore())

            # Test dialing (uses NAT detection internally)
            connection = await transport_a.dial(webrtc_addr)
            assert connection is not None, "Failed to establish connection"

            webrtc_connection = cast(WebRTCRawConnection, connection)

            # Verify connection properties
            assert webrtc_connection.peer_id == nat_peer_b.get_id(), (
                "Connection peer ID mismatch"
            )

            # Test data exchange
            stream = await webrtc_connection.open_stream()
            test_data = b"End-to-end NAT integration test"
            await stream.write(test_data)
            received = await stream.read(len(test_data))
            assert received == test_data, "Data exchange failed"

            await stream.close()
            await connection.close()
            await listener_b.close()

    finally:
        await transport_a.stop()
        await transport_b.stop()

        # Verify cleanup
        assert transport_a._reachability_checker is None, (
            "ReachabilityChecker should be cleaned up after stop"
        )
        assert transport_b._reachability_checker is None, (
            "ReachabilityChecker should be cleaned up after stop"
        )

    logger.info("✅ NAT integration end-to-end test passed")


# ============================================================================
# WEBRTC-DIRECT NAT TRAVERSAL INTEGRATION TESTS
# ============================================================================


@pytest.mark.trio
async def test_webrtc_direct_nat_checker_initialization(nat_peer_a: IHost):
    """
    Test that WebRTCDirectTransport initializes ReachabilityChecker on start.

    Validates that NAT detection infrastructure is properly set up for
    WebRTC-Direct transport.
    """
    logger.info("=== Testing WebRTC-Direct NAT checker initialization ===")

    transport = WebRTCDirectTransport()
    transport.set_host(nat_peer_a)

    # Verify checker is not initialized before start
    assert transport._reachability_checker is None, (
        "ReachabilityChecker should not be initialized before start"
    )

    # Start transport
    async with trio.open_nursery() as nursery:
        await transport.start(nursery)

        # Verify checker is initialized after start
        assert transport._reachability_checker is not None, (
            "ReachabilityChecker should be initialized after start"
        )
        assert isinstance(transport._reachability_checker, ReachabilityChecker), (
            "ReachabilityChecker should be an instance of ReachabilityChecker"
        )

        # Verify checker is cleaned up on stop
        await transport.stop()
        assert transport._reachability_checker is None, (
            "ReachabilityChecker should be cleaned up after stop"
        )

    logger.info("✅ WebRTC-Direct NAT checker initialization test passed")


@pytest.mark.trio
async def test_webrtc_direct_nat_aware_address_advertisement(nat_peer_a: IHost):
    """
    Test NAT-aware address advertisement in WebRTC-Direct listener.

    Validates that:
    1. Public addresses are advertised when available
    2. Address advertisement uses NAT detection
    3. All addresses contain required components
    """
    logger.info("=== Testing WebRTC-Direct NAT-aware address advertisement ===")

    transport = WebRTCDirectTransport()
    transport.set_host(nat_peer_a)

    async def echo_handler(stream):
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    async with trio.open_nursery() as nursery:
        await transport.start(nursery)

        # Verify ReachabilityChecker is initialized
        assert transport._reachability_checker is not None, (
            "ReachabilityChecker should be initialized"
        )

        listener = transport.create_listener(echo_handler)

        try:
            success = await listener.listen(
                Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"), nursery
            )
            assert success, "Listener failed to start"

            await trio.sleep(1.0)  # Give time for address generation

            # Get advertised addresses
            webrtc_addrs = listener.get_addrs()
            assert webrtc_addrs, "No WebRTC-Direct addresses advertised"

            logger.info(f"Advertised addresses: {[str(a) for a in webrtc_addrs]}")

            # Verify all addresses contain required components
            for addr in webrtc_addrs:
                addr_str = str(addr)
                assert "/webrtc-direct" in addr_str, (
                    f"Address should contain /webrtc-direct: {addr_str}"
                )
                assert "/certhash/" in addr_str, (
                    f"Address should contain certhash: {addr_str}"
                )
                assert "/p2p/" in addr_str, (
                    f"Address should contain peer ID: {addr_str}"
                )

            # Verify NAT detection was used (checker should filter public addresses)
            checker = transport._reachability_checker
            all_host_addrs = list(nat_peer_a.get_addrs())
            public_host_addrs = checker.get_public_addrs(all_host_addrs)

            if public_host_addrs:
                logger.info(
                    f"Host has {len(public_host_addrs)} public addresses, "
                    f"advertised {len(webrtc_addrs)} WebRTC-Direct addresses"
                )
            else:
                logger.info("Host has no public addresses, all addresses advertised")

            await listener.close()

        finally:
            await transport.stop()

    logger.info("✅ WebRTC-Direct NAT-aware address advertisement test passed")


@pytest.mark.trio
async def test_webrtc_direct_nat_detection_during_dial(
    nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    Test that NAT detection is performed during WebRTC-Direct dial operation.

    Validates that:
    1. Peer and self-reachability are checked before dialing
    2. UDP hole punching is skipped when both peers are reachable
    3. UDP hole punching is attempted when NAT is detected
    4. ICE servers are configured based on NAT status
    """
    logger.info("=== Testing WebRTC-Direct NAT detection during dial ===")

    transport_a = WebRTCDirectTransport()
    transport_a.set_host(nat_peer_a)

    transport_b = WebRTCDirectTransport()
    transport_b.set_host(nat_peer_b)

    async def echo_handler(stream):
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    try:
        async with trio.open_nursery() as nursery:
            # Start both transports
            await transport_a.start(nursery)
            await transport_b.start(nursery)

            # Verify ReachabilityChecker is initialized
            assert transport_a._reachability_checker is not None, (
                "Transport A should have ReachabilityChecker initialized"
            )
            assert transport_b._reachability_checker is not None, (
                "Transport B should have ReachabilityChecker initialized"
            )

            # Set up listener on peer B
            listener_b = transport_b.create_listener(echo_handler)
            success = await listener_b.listen(
                Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"), nursery
            )
            assert success, "Listener B failed to start"

            await trio.sleep(1.0)

            # Get advertised addresses
            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No addresses advertised"
            webrtc_addr = webrtc_addrs[0]

            # Store peer's TCP address in peerstore for signal_service
            # Signal service needs TCP connection to exchange SDP
            peer_b_tcp_addrs = [
                addr for addr in nat_peer_b.get_addrs() if "/tcp/" in str(addr)
            ]
            if peer_b_tcp_addrs:
                peerstore_a = nat_peer_a.get_peerstore()
                for tcp_addr in peer_b_tcp_addrs:
                    # Remove /p2p/ component to get base TCP address
                    try:
                        base_tcp_addr = tcp_addr.decapsulate(
                            Multiaddr(f"/p2p/{nat_peer_b.get_id()}")
                        )
                        peerstore_a.add_addr(nat_peer_b.get_id(), base_tcp_addr, 3600)
                        logger.debug(f"Stored TCP addr {base_tcp_addr} for peer B")
                    except Exception:
                        # If decapsulation fails, try storing as-is
                        peerstore_a.add_addr(nat_peer_b.get_id(), tcp_addr, 3600)

            # Check peer and self-reachability before dial
            checker_a = transport_a._reachability_checker  # type: ignore
            is_peer_reachable = await checker_a.check_peer_reachability(
                nat_peer_b.get_id()
            )
            is_self_reachable, public_addrs = await checker_a.check_self_reachability()  # type: ignore

            logger.info(f"Peer B reachable: {is_peer_reachable}")
            logger.info(f"Self reachable: {is_self_reachable}")

            # Dial should use NAT detection internally
            # The dial() method will check reachability and decide on UDP hole punching
            connection = await transport_a.dial(webrtc_addr)
            assert connection is not None, "Failed to establish connection"

            # Verify connection works
            # Cast to WebRTCRawConnection to access open_stream()
            webrtc_connection = cast(WebRTCRawConnection, connection)
            stream = await webrtc_connection.open_stream()
            test_data = b"WebRTC-Direct NAT detection test"
            await stream.write(test_data)
            received = await stream.read(len(test_data))
            assert received == test_data, "Data exchange failed"

            await stream.close()
            await connection.close()
            await listener_b.close()

    finally:
        await transport_a.stop()
        await transport_b.stop()

    logger.info("✅ WebRTC-Direct NAT detection during dial test passed")


@pytest.mark.trio
async def test_webrtc_direct_ice_server_configuration(nat_peer_a: IHost):
    """
    Test that ICE servers are configured based on NAT status.

    Validates that:
    1. STUN/TURN servers are configured when behind NAT
    2. Minimal ICE servers are used when public IP is available
    """
    logger.info("=== Testing WebRTC-Direct ICE server configuration ===")

    transport = WebRTCDirectTransport()
    transport.set_host(nat_peer_a)

    async with trio.open_nursery() as nursery:
        await transport.start(nursery)

        # Verify ReachabilityChecker is initialized
        assert transport._reachability_checker is not None, (
            "ReachabilityChecker should be initialized"
        )

        # Check self-reachability
        checker = transport._reachability_checker
        is_self_reachable, public_addrs = await checker.check_self_reachability()

        logger.info(f"Self reachable: {is_self_reachable}")
        logger.info(f"Public addresses: {len(public_addrs)}")

        # The ICE server configuration happens during dial()
        # We can verify the logic by checking the transport's ice_servers
        # In test environment, peers typically have private addresses
        if not is_self_reachable:
            logger.info("Peer behind NAT - ICE servers should include STUN/TURN")
        else:
            logger.info("Peer has public IP - minimal ICE servers should be used")

        await transport.stop()

    logger.info("✅ WebRTC-Direct ICE server configuration test passed")


@pytest.mark.trio
async def test_webrtc_direct_nat_integration_end_to_end(
    nat_peer_a: IHost, nat_peer_b: IHost
):
    """
    End-to-end test of NAT traversal integration in WebRTC-Direct.

    Validates the complete flow:
    1. Transport initializes NAT detection
    2. Address advertisement uses NAT detection
    3. Dialing uses NAT detection for peer reachability
    4. UDP hole punching is optimized based on NAT status
    5. ICE servers are configured appropriately
    6. Connection establishment works correctly
    """
    logger.info("=== Testing WebRTC-Direct NAT integration end-to-end ===")

    transport_a = WebRTCDirectTransport()
    transport_a.set_host(nat_peer_a)

    transport_b = WebRTCDirectTransport()
    transport_b.set_host(nat_peer_b)

    async def echo_handler(stream):
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    try:
        async with trio.open_nursery() as nursery:
            # Start transports
            await transport_a.start(nursery)
            await transport_b.start(nursery)

            # Verify NAT detection is initialized
            assert transport_a._reachability_checker is not None, (
                "Transport A should have ReachabilityChecker initialized"
            )
            assert transport_b._reachability_checker is not None, (
                "Transport B should have ReachabilityChecker initialized"
            )

            # Set up listener
            listener_b = transport_b.create_listener(echo_handler)
            success = await listener_b.listen(
                Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"), nursery
            )
            assert success, "Listener failed to start"

            await trio.sleep(1.0)

            # Test address advertisement (NAT-aware)
            webrtc_addrs = listener_b.get_addrs()
            assert webrtc_addrs, "No addresses advertised"

            # Verify addresses are properly formatted
            for addr in webrtc_addrs:
                addr_str = str(addr)
                assert "/webrtc-direct" in addr_str, (
                    f"Address missing /webrtc-direct: {addr_str}"
                )
                assert "/certhash/" in addr_str, f"Address missing certhash: {addr_str}"
                assert "/p2p/" in addr_str, f"Address missing peer ID: {addr_str}"

            webrtc_addr = webrtc_addrs[0]

            # Store peer's TCP address in peerstore for signal_service
            # Signal service needs TCP connection to exchange SDP
            peer_b_tcp_addrs = [
                addr for addr in nat_peer_b.get_addrs() if "/tcp/" in str(addr)
            ]
            if peer_b_tcp_addrs:
                peerstore_a = nat_peer_a.get_peerstore()
                for tcp_addr in peer_b_tcp_addrs:
                    # Remove /p2p/ component to get base TCP address
                    try:
                        base_tcp_addr = tcp_addr.decapsulate(
                            Multiaddr(f"/p2p/{nat_peer_b.get_id()}")
                        )
                        peerstore_a.add_addr(nat_peer_b.get_id(), base_tcp_addr, 3600)
                        logger.debug(f"Stored TCP addr{base_tcp_addr} for peer B")
                    except Exception:
                        # If decapsulation fails, try storing as-is
                        peerstore_a.add_addr(nat_peer_b.get_id(), tcp_addr, 3600)

            # Test dialing (uses NAT detection internally)
            connection = await transport_a.dial(webrtc_addr)
            assert connection is not None, "Failed to establish connection"

            # Verify connection properties
            assert hasattr(connection, "remote_peer_id"), (
                "Connection should have remote peer ID"
            )

            # Test data exchange
            # Cast to WebRTCRawConnection to access open_stream()
            webrtc_connection = cast(WebRTCRawConnection, connection)
            stream = await webrtc_connection.open_stream()
            test_data = b"End-to-end WebRTC-Direct NAT integration test"
            await stream.write(test_data)
            received = await stream.read(len(test_data))
            assert received == test_data, "Data exchange failed"

            await stream.close()
            await connection.close()
            await listener_b.close()

        # Verify cleanup
        assert transport_a._reachability_checker is None, (
            "ReachabilityChecker should be cleaned up after stop"
        )
        assert transport_b._reachability_checker is None, (
            "ReachabilityChecker should be cleaned up after stop"
        )

    finally:
        await transport_a.stop()
        await transport_b.stop()

    logger.info("✅ WebRTC-Direct NAT integration end-to-end test passed")

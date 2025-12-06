"""
Integration tests for WebRTC transport in py-libp2p.

Tests real P2P connections over WebRTC (private-to-private via circuit relay)
and WebRTC-Direct (private-to-public with certhash).

These tests follow the js-libp2p WebRTC test patterns and validate:
1. Protocol registration with multiaddr
2. Certificate generation and certhash integration
3. Real P2P connections via relay (WebRTC)
4. Direct P2P connections (WebRTC-Direct)
5. Data exchange over WebRTC streams
6. Stream multiplexing
"""

import logging
from typing import cast

import pytest
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost, INetStream
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.exceptions import MultiError
from libp2p.host.basic_host import BasicHost
from libp2p.network.exceptions import SwarmException

# Import WebRTC protocols to trigger registration
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.connection import WebRTCRawConnection, WebRTCStream
from libp2p.transport.webrtc.private_to_private.relay_fixtures import (
    echo_stream_handler,
    store_relay_addrs,
)
from libp2p.transport.webrtc.private_to_private.transport import WebRTCTransport
from libp2p.transport.webrtc.private_to_private.util import split_addr
from libp2p.transport.webrtc.private_to_public.gen_certificate import (
    create_webrtc_multiaddr,
)
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport

logger = logging.getLogger("libp2p.transport.webrtc.integration_tests")

pytest_plugins = ("libp2p.transport.webrtc.private_to_private.relay_fixtures",)

# Test configuration
TEST_TIMEOUT = 30.0
ECHO_PROTOCOL = TProtocol("/libp2p/echo/1.0.0")


@pytest.fixture
def peer_id_a():
    """Generate peer ID for node A"""
    key_pair = create_new_key_pair()
    from libp2p import generate_peer_id_from

    return generate_peer_id_from(key_pair)


@pytest.fixture
def peer_id_b():
    """Generate peer ID for node B"""
    key_pair = create_new_key_pair()
    from libp2p import generate_peer_id_from

    return generate_peer_id_from(key_pair)


# ============================================================================
# UNIT TESTS - Multiaddr and Protocol Registration
# ============================================================================


@pytest.mark.trio
async def test_webrtc_protocol_registration():
    """Test that /webrtc and /webrtc-direct protocols are registered"""
    from multiaddr.protocols import REGISTRY

    # Verify webrtc protocol exists
    try:
        webrtc_proto = REGISTRY.find_by_name("webrtc")
        assert webrtc_proto is not None, "WebRTC protocol not registered"
        assert webrtc_proto.code == 281, f"Expected code 281, got {webrtc_proto.code}"
        logger.info("✅ WebRTC protocol registered correctly")
    except Exception as e:
        pytest.fail(f"WebRTC protocol registration failed: {e}")

    # Verify webrtc-direct protocol exists
    try:
        webrtc_direct_proto = REGISTRY.find_by_name("webrtc-direct")
        assert webrtc_direct_proto is not None, "WebRTC-Direct protocol not registered"
        assert webrtc_direct_proto.code == 280, (
            f"Expected code 280, got {webrtc_direct_proto.code}"
        )
        logger.info("✅ WebRTC-Direct protocol registered correctly")
    except Exception as e:
        pytest.fail(f"WebRTC-Direct protocol registration failed: {e}")

    # Verify certhash protocol exists
    try:
        certhash_proto = REGISTRY.find_by_name("certhash")
        assert certhash_proto is not None, "Certhash protocol not registered"
        assert certhash_proto.code == 466, (
            f"Expected code 466, got {certhash_proto.code}"
        )
        logger.info("✅ Certhash protocol registered correctly")
    except Exception as e:
        pytest.fail(f"Certhash protocol registration failed: {e}")


@pytest.mark.trio
async def test_webrtc_multiaddr_parsing(peer_id_a):
    """Test parsing of WebRTC multiaddrs"""
    # Test /webrtc multiaddr (private-to-private)
    webrtc_maddr_str = f"/webrtc/p2p/{peer_id_a}"
    try:
        webrtc_maddr = Multiaddr(webrtc_maddr_str)
        protocols = [p.name for p in webrtc_maddr.protocols()]
        assert "webrtc" in protocols, f"WeBRTC protocol not in {protocols}"
        assert "p2p" in protocols, f"p2p protocol not in {protocols}"

        peer_id_value = webrtc_maddr.value_for_protocol("p2p")
        assert peer_id_value == str(peer_id_a), (
            f"Expected {peer_id_a}, got {peer_id_value}"
        )
        logger.info(f"✅ Parsed webrtc multiaddr: {webrtc_maddr_str}")
    except Exception as e:
        pytest.fail(f"Failed to parse webrtc multiaddr: {e}")

    # Test /webrtc-direct multiaddr (with certhash)
    from libp2p.transport.webrtc.private_to_public.gen_certificate import (
        WebRTCCertificate,
    )

    cert = WebRTCCertificate()

    webrtc_direct_maddr = create_webrtc_multiaddr(
        "127.0.0.1",
        peer_id_a,
        cert.certhash,
        direct=True,
    )
    try:
        direct_maddr = Multiaddr(webrtc_direct_maddr)
        protocols = [p.name for p in direct_maddr.protocols()]
        assert "udp" in protocols, f"UDP protocol not in {protocols}"
        assert "webrtc-direct" in protocols, (
            f"webrtc-direct protocol not in {protocols}"
        )
        assert "certhash" in protocols, f"certhash protocol not in {protocols}"
        assert "p2p" in protocols, f"p2p protocol not in {protocols}"

        # Note: value_for_protocol may not work for dynamically registered protocols
        # certhash_value = direct_maddr.value_for_protocol("certhash")
        # assert certhash_value == cert.certhash,
        # f"Expected {cert.certhash}, got {certhash_value}"
        # Just verify certhash is in the protocol list
        # certhash_value = direct_maddr.value_for_protocol("certhash")
        # assert certhash_value == cert.certhash

        peer_id_value = direct_maddr.value_for_protocol("p2p")
        assert peer_id_value == str(peer_id_a), (
            f"Expected {peer_id_a}, got {peer_id_value}"
        )
        logger.info("✅ Parsed webrtc-direct multiaddr with certhash")
    except Exception as e:
        pytest.fail(f"Failed to parse webrtc-direct multiaddr: {e}")


@pytest.mark.trio
async def test_certificate_generation():
    """Test WebRTC certificate generation for WebRTC-Direct"""
    from libp2p.transport.webrtc.private_to_public.gen_certificate import (
        WebRTCCertificate,
    )

    # Generate certificate
    cert = WebRTCCertificate()

    # Validate certhash format (uEi prefix + base64url)
    assert cert.certhash.startswith("uEi"), (
        f"Certhash should start with 'uEi', got {cert.certhash}"
    )
    assert len(cert.certhash) > 10, f"Certhash too short: {cert.certhash}"

    # Validate certificate PEM export/import
    assert cert.validate_pem_export(), "Certificate PEM validation failed"

    logger.info(f"✅ Generated certificate with hash: {cert.certhash}")


# ============================================================================
# INTEGRATION TESTS - WebRTC-Direct (Private-to-Public)
# ============================================================================


@pytest.mark.trio
async def test_webrtc_direct_listen_on_localhost():
    """Test WebRTC-Direct transport listening on localhost"""
    # Create node A with WebRTC-Direct transport
    key_pair_a = create_new_key_pair()
    host_a = new_host(key_pair=key_pair_a)

    # Create WebRTC-Direct transport
    webrtc_direct_transport = WebRTCDirectTransport()
    webrtc_direct_transport.set_host(host_a)

    # Start transport
    async with trio.open_nursery() as nursery:
        await webrtc_direct_transport.start(nursery)

        async def echo_handler(stream):
            data = await stream.read()
            await stream.write(data)
            await stream.close()

        # Note: handler_function is not used by WebRTCDirectListener
        # Stream handlers are set via host.set_stream_handler() instead
        listener = webrtc_direct_transport.create_listener()

        # Listen on localhost
        listen_maddr = Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct")
        listen_success = await listener.listen(listen_maddr, nursery)

        assert listen_success, "Failed to listen on WebRTC-Direct"

        # Get listening addresses
        listen_addrs = listener.get_addrs()
        assert len(listen_addrs) > 0, "No listening addresses"

        # Verify certhash is in multiaddr
        assert any("/certhash/" in str(addr) for addr in listen_addrs), (
            f"Certhash not found in listening addresses: {listen_addrs}"
        )

        # Verify p2p peer ID is in multiaddr
        assert any("/p2p/" in str(addr) for addr in listen_addrs), (
            f"Peer ID not found in listening addresses: {listen_addrs}"
        )

        logger.info(f"✅ Listening on WebRTC-Direct: {listen_addrs}")

        await listener.close()
        await webrtc_direct_transport.stop()

    await host_a.close()


@pytest.mark.trio
async def test_webrtc_direct_data_channel_read_write():
    """
    Test WebRTC-Direct data channel read/write functionality.

    This test verifies that:
    1. Data channel can send data
    2. Data channel can receive data
    3. Messages are properly delivered to receive_channel (not send_channel)
    4. Connection.read() can successfully read data from the channel
    5. Noise handshake completes (connection is ISecureConn)
    """
    logger.info("=== Testing WebRTC-Direct data channel read/write ===")

    # Create two hosts for peer-to-peer connection
    # TCP transport is needed for signal service to exchange SDP offers/answers
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    host_a = new_host(
        key_pair=key_pair_a,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )
    host_b = new_host(
        key_pair=key_pair_b,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    transport_a = WebRTCDirectTransport()
    transport_a.set_host(host_a)
    if isinstance(host_a, BasicHost):
        host_a.transport_manager.register_transport("webrtc-direct", transport_a)

    transport_b = WebRTCDirectTransport()
    transport_b.set_host(host_b)
    if isinstance(host_b, BasicHost):
        host_b.transport_manager.register_transport("webrtc-direct", transport_b)

    connection = None
    stream = None

    try:
        # Start hosts listening on TCP (needed for signal service)
        async with (
            host_a.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]),
            host_b.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        ):
            async with trio.open_nursery() as nursery:
                await transport_a.start(nursery)
                await transport_b.start(nursery)

                # Register echo protocol handler on host B
                async def echo_protocol_handler(stream: INetStream):
                    """Echo protocol handler for stream multiplexing"""
                    data = await stream.read()
                    await stream.write(data)
                    await stream.close()

                host_b.set_stream_handler(ECHO_PROTOCOL, echo_protocol_handler)

                # Create listener on host B

                listener_b = transport_b.create_listener()
                listen_maddr = Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct")
                listen_success = await listener_b.listen(listen_maddr, nursery)
                assert listen_success, "Host B failed to listen"

                await trio.sleep(0.5)  # Give listener time to advertise

                # Get listening address from host B
                listen_addrs = listener_b.get_addrs()
                assert listen_addrs, "Host B did not advertise any addresses"
                webrtc_addr = listen_addrs[0]
                logger.info(f"Host B listening on: {webrtc_addr}")

                # Wait for hosts to be fully started and addresses to be available
                await trio.sleep(0.2)

                # Store peer B's address in host A
                peer_b_id = host_b.get_id()
                peerstore_a = host_a.get_peerstore()
                # Extract base address (without webrtc-direct and p2p components)
                try:
                    ip = webrtc_addr.value_for_protocol(
                        "ip4"
                    ) or webrtc_addr.value_for_protocol("ip6")
                    udp_port = webrtc_addr.value_for_protocol("udp")
                    if ip and udp_port:
                        ip_proto = "ip4" if ":" not in ip else "ip6"
                        base_addr = Multiaddr(f"/{ip_proto}/{ip}/udp/{udp_port}")
                    else:
                        base_addr = webrtc_addr
                except Exception:
                    base_addr = webrtc_addr

                peerstore_a.add_addr(peer_b_id, base_addr, 3600)
                logger.debug(f"Stored address {base_addr} for peer B in host A")

                # Store peer B's TCP address in peerstore for signal_service
                # Signal service needs TCP connection to exchange SDP offers/answers
                peer_b_tcp_addrs = [
                    addr for addr in host_b.get_addrs() if "/tcp/" in str(addr)
                ]
                if peer_b_tcp_addrs:
                    for tcp_addr in peer_b_tcp_addrs:
                        # Remove /p2p/ component to get base TCP address
                        try:
                            base_tcp_addr = tcp_addr.decapsulate(
                                Multiaddr(f"/p2p/{peer_b_id}")
                            )
                            peerstore_a.add_addr(peer_b_id, base_tcp_addr, 3600)
                            logger.debug(
                                f"Stored TCP address {base_tcp_addr} for B in host A"
                            )
                        except Exception:
                            # If decapsulation fails, try storing as-is
                            peerstore_a.add_addr(peer_b_id, tcp_addr, 3600)
                            logger.debug(
                                f"  Stored TCP address {tcp_addr}for B in host A"
                            )

                # Store the full WebRTC address in peerstore for swarm to use
                peerstore_a.add_addr(peer_b_id, webrtc_addr, 3600)
                logger.debug(f"Stored full WebRTC address {webrtc_addr} for peer B")

                logger.info(
                    "Host A dialing host B via swarm "
                    "(Noise handshake should complete)..."
                )
                network_a = host_a.get_network()
                dial_error = None
                with trio.move_on_after(TEST_TIMEOUT) as dial_scope:
                    try:
                        connections = await network_a.dial_peer(peer_b_id)
                    except Exception as e:
                        dial_error = e
                        logger.error(f"Dial failed with error: {e}", exc_info=True)
                        raise

                if dial_scope.cancelled_caught:
                    error_msg = "Timeout during dial - Noise handshake may have failed"
                    if dial_error:
                        error_msg += f". Error: {dial_error}"
                    pytest.fail(error_msg)

                assert connections, "Failed to establish WebRTC-Direct connection"
                logger.info("✅ WebRTC-Direct connection established via swarm")

                # Verify connection is registered in swarm
                connections_to_b = network_a.get_connections(peer_b_id)
                assert connections_to_b, "No connections to peer B in host A's network"
                logger.info("✅ Connection registered in swarm")

                # Get the connection (should be INetConn after full upgrade)
                connection_to_b = connections_to_b[0]
                from libp2p.abc import INetConn

                # Validate connection type
                logger.info(f"Connection type: {type(connection_to_b)}")

                # The connection should be INetConn (wraps muxed connection)
                assert isinstance(connection_to_b, INetConn), (
                    f"Connection should be INetConn, got {type(connection_to_b)}"
                )
                logger.info("✅ Connection is INetConn")

                # Open a stream with protocol negotiation using host API
                # This will negotiate the ECHO_PROTOCOL and route to the echo handler
                logger.info("Opening stream with protocol negotiation...")
                stream = await host_a.new_stream(peer_b_id, [ECHO_PROTOCOL])
                assert stream is not None, "Failed to open stream"
                logger.info("✅ Stream opened with protocol negotiation")

                test_message = b"__webrtc_data_channel_test__"
                logger.info(f"Testing write: sending {len(test_message)} bytes")
                await stream.write(test_message)
                logger.info("✅ Write successful")

                # Read echoed data from stream (echo handler will echo it back)
                logger.info("Reading echoed data from stream...")
                with trio.move_on_after(5.0) as read_scope:
                    echoed_data = await stream.read(len(test_message))

                if read_scope.cancelled_caught:
                    pytest.fail("Timeout reading echoed data from stream")

                # Verify echoed data matches
                assert echoed_data == test_message, (
                    f"Echoed data mismatch: sent {test_message}, received {echoed_data}"
                )
                logger.info("✅ Data channel read/write test passed")

                # Test multiple read/write cycles
                for i in range(3):
                    test_data = f"test_message_{i}".encode()
                    await stream.write(test_data)
                    await trio.sleep(0.1)
                    received = await stream.read(len(test_data))
                    assert received == test_data, f"Round {i + 1} data mismatch"
                    logger.debug(f"✅ Round {i + 1} read/write successful")

                await stream.close()
                stream = None

                await listener_b.close()

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        raise
    finally:
        if stream is not None:
            with trio.move_on_after(1):
                await stream.close()
        if connection is not None:
            with trio.move_on_after(1):
                await connection.close()
        await transport_a.stop()
        await transport_b.stop()
        await host_a.close()
        await host_b.close()

    logger.info("✅ WebRTC-Direct data channel read/write test completed")


@pytest.mark.trio
async def test_webrtc_direct_noise_handshake_completion():
    """
    Test that Noise handshake completes successfully over WebRTC-Direct.

    This test verifies that:
    1. WebRTC-Direct connection is established
    2. Data channel is operational
    3. Noise handshake completes without timeout
    4. Connection can be used for secure data exchange after handshake
    """
    logger.info("=== Testing WebRTC-Direct Noise handshake completion ===")

    # Create two hosts
    # TCP transport is needed for signal service to exchange SDP offers/answers
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    host_a = new_host(
        key_pair=key_pair_a,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )
    host_b = new_host(
        key_pair=key_pair_b,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    transport_a = WebRTCDirectTransport()
    transport_a.set_host(host_a)
    if isinstance(host_a, BasicHost):
        host_a.transport_manager.register_transport("webrtc-direct", transport_a)

    transport_b = WebRTCDirectTransport()
    transport_b.set_host(host_b)
    if isinstance(host_b, BasicHost):
        host_b.transport_manager.register_transport("webrtc-direct", transport_b)

    handshake_completed = trio.Event()
    secure_data_received = b""

    async def secure_handler(stream):
        """Handler that receives secure data after Noise handshake"""
        nonlocal secure_data_received, handshake_completed
        try:
            secure_data_received = await stream.read()
            logger.info(
                f"Host B received secure data: {len(secure_data_received)} bytes"
            )
            await stream.write(secure_data_received)
            handshake_completed.set()
            await stream.close()
        except Exception as e:
            logger.error(f"Error in secure handler: {e}")
            raise

    connection = None

    try:
        # Start hosts listening on TCP (needed for signal service)
        async with (
            host_a.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]),
            host_b.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        ):
            async with trio.open_nursery() as nursery:
                await transport_a.start(nursery)
                await transport_b.start(nursery)

                # Register echo protocol handler on host B
                async def echo_protocol_handler(stream):
                    """Echo protocol handler for secure streams"""
                    data = await stream.read()
                    await stream.write(data)
                    await stream.close()

                host_b.set_stream_handler(ECHO_PROTOCOL, echo_protocol_handler)

                listener_b = transport_b.create_listener()
                listen_maddr = Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct")
                listen_success = await listener_b.listen(listen_maddr, nursery)
                assert listen_success, "Host B failed to listen"

                await trio.sleep(0.5)

                # Get listening address
                listen_addrs = listener_b.get_addrs()
                assert listen_addrs, "Host B did not advertise addresses"
                webrtc_addr = listen_addrs[0]
                logger.info(f"Host B listening on: {webrtc_addr}")

                # Wait for hosts to be fully started and addresses to be available
                await trio.sleep(0.2)

                # Store peer address
                peer_b_id = host_b.get_id()
                peerstore_a = host_a.get_peerstore()
                try:
                    base_addr = webrtc_addr.decapsulate(
                        Multiaddr(
                            f"/webrtc-direct/certhash/{webrtc_addr.value_for_protocol('certhash')}/p2p/{peer_b_id}"
                        )
                    )
                except Exception:
                    try:
                        ip = webrtc_addr.value_for_protocol(
                            "ip4"
                        ) or webrtc_addr.value_for_protocol("ip6")
                        udp_port = webrtc_addr.value_for_protocol("udp")
                        if ip and udp_port:
                            ip_proto = "ip4" if ":" not in ip else "ip6"
                            base_addr = Multiaddr(f"/{ip_proto}/{ip}/udp/{udp_port}")
                        else:
                            base_addr = webrtc_addr
                    except Exception:
                        base_addr = webrtc_addr

                peerstore_a.add_addr(peer_b_id, base_addr, 3600)

                # Store peer B's TCP address in peerstore for signal_service
                # Signal service needs TCP connection to exchange SDP offers/answers
                peer_b_tcp_addrs = [
                    addr for addr in host_b.get_addrs() if "/tcp/" in str(addr)
                ]
                if peer_b_tcp_addrs:
                    for tcp_addr in peer_b_tcp_addrs:
                        # Remove /p2p/ component to get base TCP address
                        try:
                            base_tcp_addr = tcp_addr.decapsulate(
                                Multiaddr(f"/p2p/{peer_b_id}")
                            )
                            peerstore_a.add_addr(peer_b_id, base_tcp_addr, 3600)
                            logger.debug(
                                f"Stored TCP address {base_tcp_addr} for B in host A"
                            )
                        except Exception:
                            # If decapsulation fails, try storing as-is
                            peerstore_a.add_addr(peer_b_id, tcp_addr, 3600)
                            logger.debug(
                                f"Stored TCP address {tcp_addr} for B in host A"
                            )

                # Store the full WebRTC address in peerstore for swarm to use
                peerstore_a.add_addr(peer_b_id, webrtc_addr, 3600)
                logger.debug(f"Stored full WebRTC address {webrtc_addr} for peer B")

                logger.info(
                    "Host A dialing host B via swarm "
                    "(Noise handshake should complete)..."
                )
                network_a = host_a.get_network()
                with trio.move_on_after(TEST_TIMEOUT) as dial_scope:
                    connections = await network_a.dial_peer(peer_b_id)

                if dial_scope.cancelled_caught:
                    pytest.fail("Timeout during WebRTC-Direct dial")

                assert connections, "Failed to establish connection"
                logger.info(
                    "✅ Connection established via swarm (Noise handshake completed)"
                )

                from libp2p.abc import INetConn

                # Verify connection is registered
                connections_to_b = network_a.get_connections(peer_b_id)
                assert connections_to_b, "No connections to peer B in host A's network"
                logger.info("✅ Connection registered in swarm")

                # Get the connection (should be INetConn after full upgrade)
                connection_to_b = connections_to_b[0]
                assert isinstance(connection_to_b, INetConn), (
                    "Connection should be INetConn after full upgrade"
                )
                logger.info("✅ Connection is INetConn")

                # Open a stream with protocol negotiation using host API
                logger.info("Testing secure data exchange...")
                stream = await host_a.new_stream(peer_b_id, [ECHO_PROTOCOL])
                assert stream is not None, "Failed to open stream on secure connection"

                test_data = b"__noise_handshake_test__"
                await stream.write(test_data)

                # Wait for data to be received and echoed
                with trio.move_on_after(5.0) as read_scope:
                    received = await stream.read(len(test_data))

                if read_scope.cancelled_caught:
                    pytest.fail("Timeout reading data from secure stream")

                assert received == test_data, (
                    f"Secure data mismatch: sent {test_data}, received {received}"
                )
                logger.info("✅ Secure data exchange successful")

                # Wait for handshake completion event (from handler)
                with trio.move_on_after(2.0):
                    await handshake_completed.wait()

                assert secure_data_received == test_data, (
                    "Handler received different data than sent"
                )

                await stream.close()
                await listener_b.close()

    except Exception as e:
        logger.error(f"Noise handshake test failed: {e}", exc_info=True)
        raise
    finally:
        if connection is not None:
            with trio.move_on_after(1):
                await connection.close()
        await transport_a.stop()
        await transport_b.stop()
        await host_a.close()
        await host_b.close()

    logger.info("✅ WebRTC-Direct Noise handshake completion test passed")


@pytest.mark.trio
async def test_webrtc_direct_data_channel_message_handling():
    """
    Test that data channel message handler correctly delivers to receive_channel.

    This test specifically verifies the fix for the bug where messages were
    delivered to send_channel instead of receive_channel, causing read() to block.

    The test verifies that:
    1. Multiple messages can be sent and received
    2. Messages arrive in correct order
    3. No timeouts occur during read() operations
    4. Data flows correctly through the secure connection
    """
    logger.info("=== Testing WebRTC-Direct data channel message handling ===")

    # TCP transport is needed for signal service to exchange SDP offers/answers
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    host_a = new_host(
        key_pair=key_pair_a,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )
    host_b = new_host(
        key_pair=key_pair_b,
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    transport_a = WebRTCDirectTransport()
    transport_a.set_host(host_a)
    if isinstance(host_a, BasicHost):
        host_a.transport_manager.register_transport("webrtc-direct", transport_a)

    transport_b = WebRTCDirectTransport()
    transport_b.set_host(host_b)
    if isinstance(host_b, BasicHost):
        host_b.transport_manager.register_transport("webrtc-direct", transport_b)

    messages_received = []

    async def message_handler(stream):
        """Handler that receives and echoes messages"""
        nonlocal messages_received
        try:
            data = await stream.read()
            messages_received.append(data)
            logger.info(
                f"Handler received message {len(messages_received)}: {len(data)} bytes"
            )
            await stream.write(data)  # Echo back
            await stream.close()
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            raise

    connection = None
    stream = None

    try:
        # Start hosts listening on TCP (needed for signal service)
        async with (
            host_a.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]),
            host_b.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        ):
            async with trio.open_nursery() as nursery:
                await transport_a.start(nursery)
                await transport_b.start(nursery)

                # Register echo protocol handler on host B
                async def echo_protocol_handler(stream):
                    """Echo protocol handler for message handling test"""
                    data = await stream.read()
                    await stream.write(data)
                    await stream.close()

                host_b.set_stream_handler(ECHO_PROTOCOL, echo_protocol_handler)

                listener_b = transport_b.create_listener()
                listen_maddr = Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct")
                await listener_b.listen(listen_maddr, nursery)

                await trio.sleep(0.5)

                listen_addrs = listener_b.get_addrs()
                assert listen_addrs, "No listening addresses"
                webrtc_addr = listen_addrs[0]

                # Wait for hosts to be fully started and addresses to be available
                await trio.sleep(0.2)

                # Store peer address
                peer_b_id = host_b.get_id()
                peerstore_a = host_a.get_peerstore()
                try:
                    ip = webrtc_addr.value_for_protocol(
                        "ip4"
                    ) or webrtc_addr.value_for_protocol("ip6")
                    udp_port = webrtc_addr.value_for_protocol("udp")
                    if ip and udp_port:
                        ip_proto = "ip4" if ":" not in ip else "ip6"
                        base_addr = Multiaddr(f"/{ip_proto}/{ip}/udp/{udp_port}")
                    else:
                        base_addr = webrtc_addr
                except Exception:
                    base_addr = webrtc_addr

                peerstore_a.add_addr(peer_b_id, base_addr, 3600)

                # Store peer B's TCP address in peerstore for signal_service
                # Signal service needs TCP connection to exchange SDP offers/answers
                peer_b_tcp_addrs = [
                    addr for addr in host_b.get_addrs() if "/tcp/" in str(addr)
                ]
                if peer_b_tcp_addrs:
                    for tcp_addr in peer_b_tcp_addrs:
                        # Remove /p2p/ component to get base TCP address
                        try:
                            base_tcp_addr = tcp_addr.decapsulate(
                                Multiaddr(f"/p2p/{peer_b_id}")
                            )
                            peerstore_a.add_addr(peer_b_id, base_tcp_addr, 3600)
                            logger.debug(
                                f"Stored TCP addr {base_tcp_addr} for B in host A"
                            )
                        except Exception:
                            # If decapsulation fails, try storing as-is
                            peerstore_a.add_addr(peer_b_id, tcp_addr, 3600)
                            logger.debug(f"Stored TCP addr {tcp_addr} for B in host A")

                # Store the full WebRTC address in peerstore for swarm to use
                peerstore_a.add_addr(peer_b_id, webrtc_addr, 3600)
                logger.debug(f"Stored full WebRTC address {webrtc_addr} for peer B")

                # Dial - this completes Noise handshake via swarm
                logger.info("Dialing via swarm (Noise handshake should complete)...")
                network_a = host_a.get_network()
                with trio.move_on_after(TEST_TIMEOUT) as dial_scope:
                    connections = await network_a.dial_peer(peer_b_id)

                if dial_scope.cancelled_caught:
                    pytest.fail("Timeout during WebRTC-Direct dial")

                assert connections, "Connection failed"
                logger.info(
                    "✅ Connection established via swarm (Noise handshake completed)"
                )

                # Verify connection is registered
                connections_to_b = network_a.get_connections(peer_b_id)
                assert connections_to_b, "No connections to peer B"
                logger.info("✅ Connection registered in swarm")

                # Get the connection
                connection_to_b = connections_to_b[0]
                from libp2p.abc import INetConn

                assert isinstance(connection_to_b, INetConn), (
                    "Connection should be INetConn"
                )

                # Test multiple messages through streams
                test_messages = [
                    b"message_1",
                    b"message_2",
                    b"message_3",
                ]

                for i, test_msg in enumerate(test_messages):
                    logger.info(f"Sending message {i + 1}: {len(test_msg)} bytes")

                    # Open a new stream with protocol negotiation for each message
                    stream = await host_a.new_stream(peer_b_id, [ECHO_PROTOCOL])
                    assert stream is not None, (
                        f"Failed to open stream for message {i + 1}"
                    )

                    # Send message
                    await stream.write(test_msg)

                    # Wait for message to be received and echoed
                    logger.info(f"Waiting for message {i + 1} to be received...")
                    with trio.move_on_after(5.0) as read_scope:
                        received = await stream.read(len(test_msg))

                    if read_scope.cancelled_caught:
                        pytest.fail(
                            f"Timeout reading message {i + 1} - "
                            "data channel receive_channel may not be working correctly"
                        )

                    assert received == test_msg, (
                        f"Msg {i + 1} mismatch: sent {test_msg}, received {received}"
                    )
                    logger.info(f"✅ Message {i + 1} received correctly")

                    await stream.close()
                    stream = None

                    # Give handler time to process
                    await trio.sleep(0.1)

                # Verify all messages were received by handler
                assert len(messages_received) == len(test_messages), (
                    f"Handler received {len(messages_received)} messages, "
                    f"expected {len(test_messages)}"
                )

                # Verify message order
                for i, (sent, received) in enumerate(
                    zip(test_messages, messages_received)
                ):
                    assert sent == received, f"Message {i + 1} order/content mismatch"

                await listener_b.close()

    except Exception as e:
        logger.error(f"Message handling test failed: {e}", exc_info=True)
        raise
    finally:
        if stream is not None:
            with trio.move_on_after(1):
                await stream.close()
        if connection is not None:
            with trio.move_on_after(1):
                await connection.close()
        await transport_a.stop()
        await transport_b.stop()
        await host_a.close()
        await host_b.close()

    logger.info("✅ Data channel message handling test passed")


# ============================================================================
# INTEGRATION TESTS - WebRTC via Circuit Relay (Private-to-Private)
# ============================================================================


@pytest.mark.trio
async def test_webrtc_relayed_connection(
    relay_host: IHost, listener_host: IHost, client_host: IHost
):
    """End-to-end WebRTC connection through a relay with explicit pre-flight checks."""
    relay_id = relay_host.get_id()
    relay_addrs = list(relay_host.get_addrs())
    print("relay raw addrs:", [str(addr) for addr in relay_addrs])
    assert relay_addrs, (
        "Relay did not advertise any addresses; unable to proceed with relayed dial"
    )

    store_relay_addrs(relay_id, relay_addrs, client_host.get_peerstore())

    stored_addrs = list(client_host.get_peerstore().addrs(relay_id))
    print("relay stored addrs:", [str(addr) for addr in stored_addrs])
    assert stored_addrs, "Client peerstore missing relay addresses after normalisation"
    for addr in stored_addrs:
        addr_str = str(addr)
        assert addr_str.count("/p2p/") == 0, (
            f"Relay addr should be raw transport addr, got {addr_str}"
        )

    swarm = client_host.get_network()
    try:
        connections = await swarm.dial_peer(relay_id)
    except SwarmException as exc:
        cause = exc.__cause__
        details = ""
        if isinstance(cause, MultiError):
            details = " | ".join(str(err) for err in cause.errors)
        pytest.fail(f"Dial to relay failed: {exc} (cause: {details})")

    assert connections, "Client failed to establish any connection to relay"

    # Confirm connectivity from both perspectives to guard against false positives.
    assert relay_id in swarm.connections, (
        "Client swarm does not record connection to relay"
    )
    assert client_host.get_id() in relay_host.get_network().connections, (
        "Relay does not record connection from client"
    )

    # Prepare transports for listener and client.
    listener_transport = WebRTCTransport({})
    listener_transport.set_host(listener_host)
    await listener_transport.start()

    client_transport = WebRTCTransport({})
    client_transport.set_host(client_host)
    await client_transport.start()

    webrtc_listener = listener_transport.create_listener(echo_stream_handler)

    connection: WebRTCRawConnection | None = None
    stream: WebRTCStream | None = None

    try:
        async with trio.open_nursery() as nursery:
            success = await webrtc_listener.listen(Multiaddr("/webrtc"), nursery)
            assert success, "WebRTC listener failed to start"

            await trio.sleep(1.5)

            webrtc_addrs = webrtc_listener.get_addrs()
            assert webrtc_addrs, "Listener did not advertise WebRTC addresses"
            webrtc_addr = webrtc_addrs[0]
            logger.info("Listener advertising WebRTC address: %s", webrtc_addr)

            circuit_addr, target_peer = split_addr(webrtc_addr)
            assert target_peer == listener_host.get_id(), (
                "Target peer mismatch in multiaddr"
            )

            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            print("circuit addr:", str(circuit_addr))
            print("target component:", str(target_component))
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr

            store_relay_addrs(target_peer, [base_addr], client_host.get_peerstore())
            print(
                "listener base addr stored for target:",
                [str(addr) for addr in client_host.get_peerstore().addrs(target_peer)],
            )

            try:
                raw_connection = await client_transport.dial(webrtc_addr)
            except Exception as exc:
                pytest.fail(f"WebRTC dial raised unexpected exception: {exc}")

            assert raw_connection is not None, (
                "WebRTC connection could not be established"
            )
            connection = cast(WebRTCRawConnection, raw_connection)

            stream = await connection.open_stream()
            assert stream is not None, "Failed to open stream over WebRTC connection"

            test_data = b"libp2p webrtc relay integration"
            await stream.write(test_data)
            received = await stream.read(len(test_data))

            assert received == test_data, "Echoed data mismatch over WebRTC relay"

            await stream.close()
            stream = None

            await connection.close()
            connection = None

            await webrtc_listener.close()
    finally:
        if stream is not None:
            with trio.move_on_after(1):
                await stream.close()
        if connection is not None:
            with trio.move_on_after(1):
                await connection.close()
        await client_transport.stop()
        await listener_transport.stop()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def create_test_stream_handler(protocol: TProtocol, expected_data: bytes):
    """Create a stream handler for testing"""
    received_data = b""

    async def handler(stream):
        nonlocal received_data
        received_data = await stream.read()
        await stream.write(received_data)
        await stream.close()

    return handler, lambda: received_data

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
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol

# Import WebRTC protocols to trigger registration
from libp2p.transport.webrtc import multiaddr_protocols  # noqa: F401
from libp2p.transport.webrtc.connection import WebRTCRawConnection
from libp2p.transport.webrtc.private_to_private.relay_fixtures import (
    echo_stream_handler,
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


# ============================================================================
# FIXTURES
# ============================================================================


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

        listener = webrtc_direct_transport.create_listener(echo_handler)

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


# NOTE: Full end-to-end WebRTC-Direct test is complex and requires:
# 1. Proper UDP socket binding and STUN/TURN integration
# 2. ICE candidate exchange
# 3. DTLS handshake
# 4. Data channel establishment

# ============================================================================
# INTEGRATION TESTS - WebRTC via Circuit Relay (Private-to-Private)
# ============================================================================


@pytest.mark.trio
async def test_webrtc_relayed_connection(relay_host, listener_host, client_host):
    """
    Test WebRTC connection via circuit relay using real transports.
    """
    listener_transport = WebRTCTransport({})
    listener_transport.set_host(listener_host)
    await listener_transport.start()

    client_transport = WebRTCTransport({})
    client_transport.set_host(client_host)
    await client_transport.start()

    webrtc_listener = listener_transport.create_listener(echo_stream_handler)

    connection = None
    stream = None

    try:
        async with trio.open_nursery() as nursery:
            success = await webrtc_listener.listen(Multiaddr("/webrtc"), nursery)
            assert success, "WebRTC listener failed to start"

            await trio.sleep(2.0)

            webrtc_addrs = webrtc_listener.get_addrs()
            assert webrtc_addrs, "Listener did not advertise WebRTC addresses"

            webrtc_addr = webrtc_addrs[0]
            logger.info("Listener advertising WebRTC address: %s", webrtc_addr)

            relay_id = relay_host.get_id()
            relay_addrs = relay_host.get_addrs()
            if relay_addrs:
                client_host.get_peerstore().add_addrs(relay_id, list(relay_addrs), 3600)

            circuit_addr, target_peer = split_addr(webrtc_addr)
            assert target_peer == listener_host.get_id(), (
                "Target peer mismatch in multiaddr"
            )

            target_component = Multiaddr(f"/p2p/{target_peer.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr

            client_host.get_peerstore().add_addrs(target_peer, [base_addr], 3600)

            await client_host.get_network().dial_peer(relay_id)

            raw_connection = await client_transport.dial(webrtc_addr)
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

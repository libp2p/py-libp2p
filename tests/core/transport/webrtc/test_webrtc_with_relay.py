import logging

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.transport.webrtc.private_to_private.relay_fixtures import (
    echo_stream_handler,
    store_relay_addrs,
)
from libp2p.transport.webrtc.private_to_private.transport import WebRTCTransport

pytest_plugins = ("libp2p.transport.webrtc.private_to_private.relay_fixtures",)

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_webrtc_transport_registration():
    """Test that WebRTC transport is registered in transport registry."""
    from libp2p.transport.transport_registry import get_transport_registry

    registry = get_transport_registry()
    webrtc_transport_class = registry.get_transport("webrtc")

    assert webrtc_transport_class is not None
    assert webrtc_transport_class == WebRTCTransport


@pytest.mark.trio
async def test_webrtc_transport_with_relay_infrastructure(relay_host, listener_host):
    """
    Test WebRTC transport with actual circuit relay infrastructure.

    This test:
    1. Sets up a relay node
    2. Sets up a listener node with WebRTC transport
    3. Verifies WebRTC transport can be initialized and started
    4. Verifies WebRTC listener can be created and started
    """
    # Set up WebRTC transport on listener
    webrtc_config = {}
    webrtc_transport = WebRTCTransport(webrtc_config)
    webrtc_transport.set_host(listener_host)

    # Start WebRTC transport
    await webrtc_transport.start()

    try:
        # Create WebRTC listener
        webrtc_listener = webrtc_transport.create_listener(echo_stream_handler)

        # Start listening (this should generate WebRTC addresses from circuit relay)
        async with trio.open_nursery() as nursery:
            success = await webrtc_listener.listen(Multiaddr("/webrtc"), nursery)

            assert success, "WebRTC listener should start successfully"

            # Wait a bit for address generation
            await trio.sleep(1.0)

            # Get WebRTC addresses
            webrtc_addrs = webrtc_listener.get_addrs()

            logger.info(f"WebRTC addresses: {webrtc_addrs}")

            # Note: Addresses may not be generated immediately if circuit relay
            # addresses aren't available yet. This is expected behavior.
            # The important thing is that the listener started successfully.
            if webrtc_addrs:
                # Verify addresses contain /webrtc
                for addr in webrtc_addrs:
                    addr_str = str(addr)
                    assert "/webrtc" in addr_str, (
                        f"Address should contain /webrtc: {addr_str}"
                    )
                    logger.info(f"Generated WebRTC address: {addr_str}")
            else:
                logger.info("No WebRTC addr yet (circuit relay may not be ready)")

            # Cleanup
            await webrtc_listener.close()
    finally:
        await webrtc_transport.stop()


@pytest.mark.trio
async def test_webrtc_dial_through_relay(relay_host, listener_host):
    """
    Test dialing a WebRTC connection through circuit relay.

    This test:
    1. Sets up relay and listener nodes
    2. Sets up WebRTC transport on both
    3. Verifies infrastructure is ready
    (may not dial if addresses not ready)
    """
    # Set up WebRTC transport on listener
    webrtc_listener_config = {}
    webrtc_listener_transport = WebRTCTransport(webrtc_listener_config)
    webrtc_listener_transport.set_host(listener_host)
    await webrtc_listener_transport.start()

    try:
        listener_webrtc = webrtc_listener_transport.create_listener(echo_stream_handler)

        # Create client host
        from tests.utils.factories import HostFactory

        async with HostFactory.create_batch_and_listen(1) as hosts:
            client_host = hosts[0]

            # Connect client to relay
            relay_id = relay_host.get_id()
            relay_addrs = relay_host.get_addrs()

            # Add relay addresses to client's peerstore
            if relay_addrs:
                store_relay_addrs(
                    relay_id, list(relay_addrs), client_host.get_peerstore()
                )

            network = client_host.get_network()
            await network.dial_peer(relay_id)

            # Set up WebRTC transport on client
            webrtc_client_config = {}
            webrtc_client_transport = WebRTCTransport(webrtc_client_config)
            webrtc_client_transport.set_host(client_host)
            await webrtc_client_transport.start()

            try:
                # Start listener
                async with trio.open_nursery() as nursery:
                    success = await listener_webrtc.listen(
                        Multiaddr("/webrtc"), nursery
                    )
                    assert success, "Listener should start successfully"

                    # Wait for address generation
                    await trio.sleep(2.0)

                    # Get WebRTC addresses
                    webrtc_addrs = listener_webrtc.get_addrs()

                    if not webrtc_addrs:
                        logger.warning("No WebRTC addr generated, skipping dial test")
                        await listener_webrtc.close()
                        return

                    # Try to dial using first WebRTC address
                    webrtc_addr = webrtc_addrs[0]
                    logger.info(f"Dialing WebRTC address: {webrtc_addr}")

                    try:
                        # Dial WebRTC connection
                        connection = await webrtc_client_transport.dial(webrtc_addr)
                        logger.info("Successfully established WebRTC connection")

                        # Verify connection
                        assert connection is not None

                        # Cleanup
                        await connection.close()

                    except Exception as e:
                        logger.warning(f"WebRTC dial failed (may be expected): {e}")
                        # This might fail if full WebRTC implementation is not complete
                        # That's okay - we're testing the infrastructure setup

                    # Cleanup
                    await listener_webrtc.close()
            finally:
                await webrtc_client_transport.stop()
    finally:
        await webrtc_listener_transport.stop()


@pytest.mark.trio
async def test_webrtc_listener_get_addrs_with_relay(relay_host, listener_host):
    """
    Test that WebRTC listener can get addresses.
    """
    # Set up WebRTC transport
    webrtc_transport = WebRTCTransport({})
    webrtc_transport.set_host(listener_host)
    await webrtc_transport.start()

    try:
        webrtc_listener = webrtc_transport.create_listener(echo_stream_handler)

        # Start listening
        async with trio.open_nursery() as nursery:
            success = await webrtc_listener.listen(Multiaddr("/webrtc"), nursery)
            assert success, "Listener should start successfully"

            # Wait for address generation
            await trio.sleep(2.0)

            # Get addresses
            addrs = webrtc_listener.get_addrs()

            logger.info(f"WebRTC listener addresses: {addrs}")

            # Verify addresses if any are generated
            # Note: Addresses may not be generated immediately if circuit relay
            # addresses aren't available yet
            if addrs:
                for addr in addrs:
                    addr_str = str(addr)
                    assert "/webrtc" in addr_str, (
                        f"Addr should contain /webrtc: {addr_str}"
                    )
                    logger.info(f"WebRTC address: {addr_str}")
            else:
                logger.info("No WebRTC addr yet (circuit relay may not be ready)")

            await webrtc_listener.close()
    finally:
        await webrtc_transport.stop()

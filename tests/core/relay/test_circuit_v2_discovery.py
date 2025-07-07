"""Tests for the Circuit Relay v2 discovery functionality."""

import logging
import time

import pytest
import trio

from libp2p.relay.circuit_v2.discovery import (
    RelayDiscovery,
)
from libp2p.relay.circuit_v2.pb import circuit_pb2 as proto
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID,
    STOP_PROTOCOL_ID,
)
from libp2p.tools.async_service import (
    background_trio_service,
)
from libp2p.tools.constants import (
    MAX_READ_LEN,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    HostFactory,
)

logger = logging.getLogger(__name__)

# Test timeouts
CONNECT_TIMEOUT = 15  # seconds
STREAM_TIMEOUT = 15  # seconds
HANDLER_TIMEOUT = 15  # seconds
SLEEP_TIME = 1.0  # seconds
DISCOVERY_TIMEOUT = 20  # seconds


# Make a simple stream handler for testing
async def simple_stream_handler(stream):
    """Simple stream handler that reads a message and responds with OK status."""
    logger.info("Simple stream handler invoked")
    try:
        # Read the request
        request_data = await stream.read(MAX_READ_LEN)
        if not request_data:
            logger.error("Empty request received")
            return

        # Parse request
        request = proto.HopMessage()
        request.ParseFromString(request_data)
        logger.info("Received request: type=%s", request.type)

        # Only handle RESERVE requests
        if request.type == proto.HopMessage.RESERVE:
            # Create a valid response
            response = proto.HopMessage(
                type=proto.HopMessage.RESERVE,
                status=proto.Status(
                    code=proto.Status.OK,
                    message="Test reservation accepted",
                ),
                reservation=proto.Reservation(
                    expire=int(time.time()) + 3600,  # 1 hour from now
                    voucher=b"test-voucher",
                    signature=b"",
                ),
                limit=proto.Limit(
                    duration=3600,  # 1 hour
                    data=1024 * 1024 * 1024,  # 1GB
                ),
            )

            # Send the response
            logger.info("Sending response")
            await stream.write(response.SerializeToString())
            logger.info("Response sent")
    except Exception as e:
        logger.error("Error in simple stream handler: %s", str(e))
    finally:
        # Keep stream open to allow client to read response
        await trio.sleep(1)
        await stream.close()


@pytest.mark.trio
async def test_relay_discovery_initialization():
    """Test Circuit v2 relay discovery initializes correctly with default settings."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        discovery = RelayDiscovery(host)

        async with background_trio_service(discovery):
            await discovery.event_started.wait()
            await trio.sleep(SLEEP_TIME)  # Give time for discovery to start

            # Verify discovery is initialized correctly
            assert discovery.host == host, "Host not set correctly"
            assert discovery.is_running, "Discovery service should be running"
            assert hasattr(discovery, "_discovered_relays"), (
                "Discovery should track discovered relays"
            )


@pytest.mark.trio
async def test_relay_discovery_find_relay_peerstore_method():
    """Test finding a relay node via discovery using the peerstore method."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        relay_host, client_host = hosts
        logger.info("Created host for test_relay_discovery_find_relay_peerstore_method")
        logger.info("Relay host ID: %s", relay_host.get_id())
        logger.info("Client host ID: %s", client_host.get_id())

        # Explicitly register the protocol handlers on relay_host
        relay_host.set_stream_handler(PROTOCOL_ID, simple_stream_handler)
        relay_host.set_stream_handler(STOP_PROTOCOL_ID, simple_stream_handler)

        # Manually add protocol to peerstore for testing
        # This simulates what the real relay protocol would do
        client_host.get_peerstore().add_protocols(
            relay_host.get_id(), [str(PROTOCOL_ID)]
        )

        # Set up discovery on the client host
        client_discovery = RelayDiscovery(
            client_host, discovery_interval=5
        )  # Use shorter interval for testing

        try:
            # Connect peers so they can discover each other
            with trio.fail_after(CONNECT_TIMEOUT):
                logger.info("Connecting client host to relay host")
                await connect(client_host, relay_host)
                assert relay_host.get_network().connections[client_host.get_id()], (
                    "Peers not connected"
                )
                logger.info("Connection established between peers")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Start discovery service
        async with background_trio_service(client_discovery):
            await client_discovery.event_started.wait()
            logger.info("Client discovery service started (peerstore method)")

            # Wait for discovery to find the relay using the peerstore method
            logger.info("Waiting for relay discovery using peerstore...")

            # Manually trigger discovery which uses peerstore as default
            await client_discovery.discover_relays()

            # Check if relay was found
            with trio.fail_after(DISCOVERY_TIMEOUT):
                for _ in range(20):  # Try multiple times
                    if relay_host.get_id() in client_discovery._discovered_relays:
                        logger.info("Relay discovered successfully (peerstore method)")
                        break

                    # Wait and try again
                    await trio.sleep(1)
                    # Manually trigger discovery again
                    await client_discovery.discover_relays()
                else:
                    pytest.fail(
                        "Failed to discover relay node within timeout(peerstore method)"
                    )

            # Verify that relay was found and is valid
            assert relay_host.get_id() in client_discovery._discovered_relays, (
                "Relay should be discovered (peerstore method)"
            )
            relay_info = client_discovery._discovered_relays[relay_host.get_id()]
            assert relay_info.peer_id == relay_host.get_id(), (
                "Peer ID should match (peerstore method)"
            )


@pytest.mark.trio
async def test_relay_discovery_find_relay_direct_connection_method():
    """Test finding a relay node via discovery using the direct connection method."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        relay_host, client_host = hosts
        logger.info("Created hosts for test_relay_discovery_find_relay_direct_method")
        logger.info("Relay host ID: %s", relay_host.get_id())
        logger.info("Client host ID: %s", client_host.get_id())

        # Explicitly register the protocol handlers on relay_host
        relay_host.set_stream_handler(PROTOCOL_ID, simple_stream_handler)
        relay_host.set_stream_handler(STOP_PROTOCOL_ID, simple_stream_handler)

        # Manually add protocol to peerstore for testing, then remove to force fallback
        client_host.get_peerstore().add_protocols(
            relay_host.get_id(), [str(PROTOCOL_ID)]
        )

        # Set up discovery on the client host
        client_discovery = RelayDiscovery(
            client_host, discovery_interval=5
        )  # Use shorter interval for testing

        try:
            # Connect peers so they can discover each other
            with trio.fail_after(CONNECT_TIMEOUT):
                logger.info("Connecting client host to relay host")
                await connect(client_host, relay_host)
                assert relay_host.get_network().connections[client_host.get_id()], (
                    "Peers not connected"
                )
                logger.info("Connection established between peers")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Remove the relay from the peerstore to test fallback to direct connection
        client_host.get_peerstore().clear_peerdata(relay_host.get_id())
        # Make sure that peer_id is not present in peerstore
        assert relay_host.get_id() not in client_host.get_peerstore().peer_ids()

        # Start discovery service
        async with background_trio_service(client_discovery):
            await client_discovery.event_started.wait()
            logger.info("Client discovery service started (direct connection method)")

            # Wait for discovery to find the relay using the direct connection method
            logger.info(
                "Waiting for relay discovery using direct connection fallback..."
            )

            # Manually trigger discovery which should fallback to direct connection
            await client_discovery.discover_relays()

            # Check if relay was found
            with trio.fail_after(DISCOVERY_TIMEOUT):
                for _ in range(20):  # Try multiple times
                    if relay_host.get_id() in client_discovery._discovered_relays:
                        logger.info("Relay discovered successfully (direct method)")
                        break

                    # Wait and try again
                    await trio.sleep(1)
                    # Manually trigger discovery again
                    await client_discovery.discover_relays()
                else:
                    pytest.fail(
                        "Failed to discover relay node within timeout (direct method)"
                    )

            # Verify that relay was found and is valid
            assert relay_host.get_id() in client_discovery._discovered_relays, (
                "Relay should be discovered (direct method)"
            )
            relay_info = client_discovery._discovered_relays[relay_host.get_id()]
            assert relay_info.peer_id == relay_host.get_id(), (
                "Peer ID should match (direct method)"
            )


@pytest.mark.trio
async def test_relay_discovery_find_relay_mux_method():
    """
    Test finding a relay node via discovery using the mux method
    (fallback after direct connection fails).
    """
    async with HostFactory.create_batch_and_listen(2) as hosts:
        relay_host, client_host = hosts
        logger.info("Created hosts for test_relay_discovery_find_relay_mux_method")
        logger.info("Relay host ID: %s", relay_host.get_id())
        logger.info("Client host ID: %s", client_host.get_id())

        # Explicitly register the protocol handlers on relay_host
        relay_host.set_stream_handler(PROTOCOL_ID, simple_stream_handler)
        relay_host.set_stream_handler(STOP_PROTOCOL_ID, simple_stream_handler)

        client_host.set_stream_handler(PROTOCOL_ID, simple_stream_handler)
        client_host.set_stream_handler(STOP_PROTOCOL_ID, simple_stream_handler)

        # Set up discovery on the client host
        client_discovery = RelayDiscovery(
            client_host, discovery_interval=5
        )  # Use shorter interval for testing

        try:
            # Connect peers so they can discover each other
            with trio.fail_after(CONNECT_TIMEOUT):
                logger.info("Connecting client host to relay host")
                await connect(client_host, relay_host)
                assert relay_host.get_network().connections[client_host.get_id()], (
                    "Peers not connected"
                )
                logger.info("Connection established between peers")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Remove the relay from the peerstore to test fallback
        client_host.get_peerstore().clear_peerdata(relay_host.get_id())
        # Make sure that peer_id is not present in peerstore
        assert relay_host.get_id() not in client_host.get_peerstore().peer_ids()

        # Mock the _check_via_direct_connection method to return None
        # This forces the discovery to fall back to the mux method
        async def mock_direct_check_fails(peer_id):
            """Mock that always returns None to force mux fallback."""
            return None

        client_discovery._check_via_direct_connection = mock_direct_check_fails

        # Start discovery service
        async with background_trio_service(client_discovery):
            await client_discovery.event_started.wait()
            logger.info("Client discovery service started (mux method)")

            # Wait for discovery to find the relay using the mux method
            logger.info("Waiting for relay discovery using mux fallback...")

            # Manually trigger discovery which should fallback to mux method
            await client_discovery.discover_relays()

            # Check if relay was found
            with trio.fail_after(DISCOVERY_TIMEOUT):
                for _ in range(20):  # Try multiple times
                    if relay_host.get_id() in client_discovery._discovered_relays:
                        logger.info("Relay discovered successfully (mux method)")
                        break

                    # Wait and try again
                    await trio.sleep(1)
                    # Manually trigger discovery again
                    await client_discovery.discover_relays()
                else:
                    pytest.fail(
                        "Failed to discover relay node within timeout (mux method)"
                    )

            # Verify that relay was found and is valid
            assert relay_host.get_id() in client_discovery._discovered_relays, (
                "Relay should be discovered (mux method)"
            )
            relay_info = client_discovery._discovered_relays[relay_host.get_id()]
            assert relay_info.peer_id == relay_host.get_id(), (
                "Peer ID should match (mux method)"
            )

            # Verify that the protocol was cached via mux method
            assert relay_host.get_id() in client_discovery._protocol_cache, (
                "Protocol should be cached (mux method)"
            )
            assert (
                str(PROTOCOL_ID)
                in client_discovery._protocol_cache[relay_host.get_id()]
            ), "Relay protocol should be in cache (mux method)"


@pytest.mark.trio
async def test_relay_discovery_auto_reservation():
    """Test that discovery can auto-reserve with discovered relays."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        relay_host, client_host = hosts
        logger.info("Created hosts for test_relay_discovery_auto_reservation")
        logger.info("Relay host ID: %s", relay_host.get_id())
        logger.info("Client host ID: %s", client_host.get_id())

        # Explicitly register the protocol handlers on relay_host
        relay_host.set_stream_handler(PROTOCOL_ID, simple_stream_handler)
        relay_host.set_stream_handler(STOP_PROTOCOL_ID, simple_stream_handler)

        # Manually add protocol to peerstore for testing
        client_host.get_peerstore().add_protocols(
            relay_host.get_id(), [str(PROTOCOL_ID)]
        )

        # Set up discovery on the client host with auto-reservation enabled
        client_discovery = RelayDiscovery(
            client_host, auto_reserve=True, discovery_interval=5
        )

        try:
            # Connect peers so they can discover each other
            with trio.fail_after(CONNECT_TIMEOUT):
                logger.info("Connecting client host to relay host")
                await connect(client_host, relay_host)
                assert relay_host.get_network().connections[client_host.get_id()], (
                    "Peers not connected"
                )
                logger.info("Connection established between peers")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Start discovery service
        async with background_trio_service(client_discovery):
            await client_discovery.event_started.wait()
            logger.info("Client discovery service started")

            # Wait for discovery to find the relay and make a reservation
            logger.info("Waiting for relay discovery and auto-reservation...")

            # Manually trigger discovery
            await client_discovery.discover_relays()

            # Check if relay was found and reservation was made
            with trio.fail_after(DISCOVERY_TIMEOUT):
                for _ in range(20):  # Try multiple times
                    relay_found = (
                        relay_host.get_id() in client_discovery._discovered_relays
                    )
                    has_reservation = (
                        relay_found
                        and client_discovery._discovered_relays[
                            relay_host.get_id()
                        ].has_reservation
                    )
                    if has_reservation:
                        logger.info(
                            "Relay discovered and reservation made successfully"
                        )
                        break

                    # Wait and try again
                    await trio.sleep(1)
                    # Try to make reservation manually
                    if relay_host.get_id() in client_discovery._discovered_relays:
                        await client_discovery.make_reservation(relay_host.get_id())
                else:
                    pytest.fail(
                        "Failed to discover relay and make reservation within timeout"
                    )

            # Verify that relay was found and reservation was made
            assert relay_host.get_id() in client_discovery._discovered_relays, (
                "Relay should be discovered"
            )
            relay_info = client_discovery._discovered_relays[relay_host.get_id()]
            assert relay_info.has_reservation, "Reservation should be made"
            assert relay_info.reservation_expires_at is not None, (
                "Reservation should have expiry time"
            )
            assert relay_info.reservation_data_limit is not None, (
                "Reservation should have data limit"
            )

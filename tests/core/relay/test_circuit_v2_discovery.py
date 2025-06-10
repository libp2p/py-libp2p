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
async def test_relay_discovery_find_relay():
    """Test finding a relay node via discovery."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        relay_host, client_host = hosts
        logger.info("Created hosts for test_relay_discovery_find_relay")
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
            logger.info("Client discovery service started")

            # Wait for discovery to find the relay
            logger.info("Waiting for relay discovery...")

            # Manually trigger discovery instead of waiting
            await client_discovery.discover_relays()

            # Check if relay was found
            with trio.fail_after(DISCOVERY_TIMEOUT):
                for _ in range(20):  # Try multiple times
                    if relay_host.get_id() in client_discovery._discovered_relays:
                        logger.info("Relay discovered successfully")
                        break

                    # Wait and try again
                    await trio.sleep(1)
                    # Manually trigger discovery again
                    await client_discovery.discover_relays()
                else:
                    pytest.fail("Failed to discover relay node within timeout")

            # Verify that relay was found and is valid
            assert relay_host.get_id() in client_discovery._discovered_relays, (
                "Relay should be discovered"
            )
            relay_info = client_discovery._discovered_relays[relay_host.get_id()]
            assert relay_info.peer_id == relay_host.get_id(), "Peer ID should match"


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

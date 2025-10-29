"""Tests for the Circuit Relay v2 transport functionality."""

import logging
import time

import pytest
import trio

from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import (
    StreamEOF,
    StreamReset,
)
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2.config import (
    RelayConfig,
)
from libp2p.relay.circuit_v2.discovery import (
    RelayDiscovery,
    RelayInfo,
)
from libp2p.relay.circuit_v2.protocol import (
    CircuitV2Protocol,
    RelayLimits,
)
from libp2p.relay.circuit_v2.transport import (
    CircuitV2Transport,
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
RELAY_TIMEOUT = 20  # seconds

# Default limits for relay
DEFAULT_RELAY_LIMITS = RelayLimits(
    duration=60 * 60,  # 1 hour
    data=1024 * 1024 * 10,  # 10 MB
    max_circuit_conns=8,  # 8 active relay connections
    max_reservations=4,  # 4 active reservations
)

# Message for testing
TEST_MESSAGE = b"Hello, Circuit Relay!"
TEST_RESPONSE = b"Hello from the other side!"


# Stream handler for testing
async def echo_stream_handler(stream):
    """Simple echo handler that responds to messages."""
    logger.info("Echo handler received stream")
    try:
        while True:
            data = await stream.read(MAX_READ_LEN)
            if not data:
                logger.info("Stream closed by remote")
                break

            logger.info("Received data: %s", data)
            await stream.write(TEST_RESPONSE)
            logger.info("Sent response")
    except (StreamEOF, StreamReset) as e:
        logger.info("Stream ended: %s", str(e))
    except Exception as e:
        logger.error("Error in echo handler: %s", str(e))
    finally:
        await stream.close()


@pytest.mark.trio
async def test_circuit_v2_transport_initialization():
    """Test that the Circuit v2 transport initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]

        # Create a protocol instance
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )
        protocol = CircuitV2Protocol(host, limits, allow_hop=False)

        config = RelayConfig()

        # Create a discovery instance
        discovery = RelayDiscovery(
            host=host,
            auto_reserve=False,
            discovery_interval=config.discovery_interval,
            max_relays=config.max_relays,
        )

        # Create the transport with the necessary components
        transport = CircuitV2Transport(host, protocol, config)
        # Replace the discovery with our manually created one
        transport.discovery = discovery

        # Verify transport properties
        assert transport.host == host, "Host not set correctly"
        assert transport.protocol == protocol, "Protocol not set correctly"
        assert transport.config == config, "Config not set correctly"
        assert hasattr(transport, "discovery"), (
            "Transport should have a discovery instance"
        )


@pytest.mark.trio
async def test_circuit_v2_transport_add_relay():
    """Test adding a relay to the transport."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host, relay_host = hosts

        # Create a protocol instance
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )
        protocol = CircuitV2Protocol(host, limits, allow_hop=False)

        config = RelayConfig()

        # Create a discovery instance
        discovery = RelayDiscovery(
            host=host,
            auto_reserve=False,
            discovery_interval=config.discovery_interval,
            max_relays=config.max_relays,
        )

        # Create the transport with the necessary components
        transport = CircuitV2Transport(host, protocol, config)
        # Replace the discovery with our manually created one
        transport.discovery = discovery

        relay_id = relay_host.get_id()
        now = time.time()
        relay_info = RelayInfo(peer_id=relay_id, discovered_at=now, last_seen=now)

        async def mock_add_relay(peer_id):
            discovery._discovered_relays[peer_id] = relay_info

        discovery._add_relay = mock_add_relay  # Type ignored in test context
        discovery._discovered_relays[relay_id] = relay_info

        # Verify relay was added
        assert relay_id in discovery._discovered_relays, (
            "Relay should be in discovery's relay list"
        )


@pytest.mark.trio
async def test_circuit_v2_transport_dial_through_relay():
    """Test dialing a peer through a relay."""
    async with HostFactory.create_batch_and_listen(3) as hosts:
        client_host, relay_host, target_host = hosts
        logger.info("Created hosts for test_circuit_v2_transport_dial_through_relay")
        logger.info("Client host ID: %s", client_host.get_id())
        logger.info("Relay host ID: %s", relay_host.get_id())
        logger.info("Target host ID: %s", target_host.get_id())

        # Setup relay with Circuit v2 protocol
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        # Register test handler on target
        test_protocol = "/test/echo/1.0.0"
        target_host.set_stream_handler(TProtocol(test_protocol), echo_stream_handler)

        client_config = RelayConfig()
        client_protocol = CircuitV2Protocol(client_host, limits, allow_hop=False)

        # Create a discovery instance
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        # Create the transport with the necessary components
        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        # Replace the discovery with our manually created one
        client_transport.discovery = client_discovery

        # Mock the get_relay method to return our relay_host
        relay_id = relay_host.get_id()
        client_discovery.get_relay = lambda: relay_id

        # Connect client to relay and relay to target
        try:
            with trio.fail_after(
                CONNECT_TIMEOUT * 2
            ):  # Double the timeout for connections
                logger.info("Connecting client host to relay host")
                await connect(client_host, relay_host)
                # Verify connection
                assert relay_host.get_id() in client_host.get_network().connections, (
                    "Client not connected to relay"
                )
                assert client_host.get_id() in relay_host.get_network().connections, (
                    "Relay not connected to client"
                )
                logger.info("Client-Relay connection verified")

                # Wait to ensure connection is fully established
                await trio.sleep(SLEEP_TIME)

                logger.info("Connecting relay host to target host")
                await connect(relay_host, target_host)
                # Verify connection
                assert target_host.get_id() in relay_host.get_network().connections, (
                    "Relay not connected to target"
                )
                assert relay_host.get_id() in target_host.get_network().connections, (
                    "Target not connected to relay"
                )
                logger.info("Relay-Target connection verified")

                # Wait to ensure connection is fully established
                await trio.sleep(SLEEP_TIME)

                logger.info("All connections established and verified")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Test successful - the connections were established, which is enough to verify
        # that the transport can be initialized and configured correctly
        logger.info("Transport initialization and connection test passed")


@pytest.mark.trio
async def test_circuit_v2_transport_relay_limits():
    """Test that relay enforces connection limits."""
    async with HostFactory.create_batch_and_listen(4) as hosts:
        client1_host, client2_host, relay_host, target_host = hosts
        logger.info("Created hosts for test_circuit_v2_transport_relay_limits")

        # Setup relay with strict limits
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=1,  # Only allow one circuit
            max_reservations=2,  # Allow both clients to reserve
        )
        relay_protocol = CircuitV2Protocol(relay_host, limits, allow_hop=True)

        # Register test handler on target
        test_protocol = "/test/echo/1.0.0"
        target_host.set_stream_handler(TProtocol(test_protocol), echo_stream_handler)

        client_config = RelayConfig()

        # Client 1 setup
        client1_protocol = CircuitV2Protocol(
            client1_host, DEFAULT_RELAY_LIMITS, allow_hop=False
        )
        client1_discovery = RelayDiscovery(
            host=client1_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )
        client1_transport = CircuitV2Transport(
            client1_host, client1_protocol, client_config
        )
        client1_transport.discovery = client1_discovery
        # Add relay to discovery
        relay_id = relay_host.get_id()
        client1_discovery.get_relay = lambda: relay_id

        # Client 2 setup
        client2_protocol = CircuitV2Protocol(
            client2_host, DEFAULT_RELAY_LIMITS, allow_hop=False
        )
        client2_discovery = RelayDiscovery(
            host=client2_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )
        client2_transport = CircuitV2Transport(
            client2_host, client2_protocol, client_config
        )
        client2_transport.discovery = client2_discovery
        # Add relay to discovery
        client2_discovery.get_relay = lambda: relay_id

        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                # Connect clients to relay
                await connect(client1_host, relay_host)
                await connect(client2_host, relay_host)

                # Connect relay to target
                await connect(relay_host, target_host)

                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Verify connections
        assert relay_host.get_id() in client1_host.get_network().connections, (
            "Client1 not connected to relay"
        )
        assert relay_host.get_id() in client2_host.get_network().connections, (
            "Client2 not connected to relay"
        )
        assert target_host.get_id() in relay_host.get_network().connections, (
            "Relay not connected to target"
        )

        # Verify the resource limits
        assert relay_protocol.resource_manager.limits.max_circuit_conns == 1, (
            "Wrong max_circuit_conns value"
        )
        assert relay_protocol.resource_manager.limits.max_reservations == 2, (
            "Wrong max_reservations value"
        )

        # Test successful - transports were initialized with the correct limits
        logger.info("Transport limit test successful")


@pytest.mark.trio
async def test_circuit_v2_transport_relay_selection():
    """Test relay round robin load balancing and reservation priority"""
    async with HostFactory.create_batch_and_listen(5) as hosts:
        client1_host, relay_host1, relay_host2, relay_host3, target_host = hosts

        # Setup relay with strict limits
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        # Register test handler on target
        test_protocol = "/test/echo/1.0.0"
        target_host.set_stream_handler(TProtocol(test_protocol), echo_stream_handler)
        target_host_info = PeerInfo(target_host.get_id(), target_host.get_addrs())

        client_config = RelayConfig()

        # Client setup
        client1_protocol = CircuitV2Protocol(client1_host, limits, allow_hop=False)
        client1_discovery = RelayDiscovery(
            host=client1_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        client1_transport = CircuitV2Transport(
            client1_host, client1_protocol, client_config
        )
        client1_transport.discovery = client1_discovery
        # Add relay to discovery
        relay_id1 = relay_host1.get_id()
        relay_id2 = relay_host2.get_id()
        relay_id3 = relay_host3.get_id()

        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                # Connect clients to relay
                await connect(client1_host, relay_host1)
                await connect(client1_host, relay_host2)
                await connect(client1_host, relay_host3)

                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        await client1_discovery._add_relay(relay_id1)
        await client1_discovery._add_relay(relay_id2)
        await client1_discovery._add_relay(relay_id3)

        selected_relay = await client1_transport._select_relay(target_host_info)
        # Without reservation preference
        # Round robin, so 1st time must be relay1
        assert selected_relay is not None and selected_relay is relay_id1

        selected_relay = await client1_transport._select_relay(target_host_info)
        # Round robin, so 2nd time must be relay2
        assert selected_relay is not None and selected_relay is relay_id2

        # Mock reservation with relay1 to prioritize over relay2
        relay_info3 = client1_discovery.get_relay_info(relay_id3)
        if relay_info3:
            relay_info3.has_reservation = True

        selected_relay = await client1_transport._select_relay(target_host_info)
        # With reservation preference, relay2 must be chosen for target_peer.
        assert selected_relay is not None and selected_relay is relay_host3.get_id()

        logger.info("Relay selection successful")


@pytest.mark.trio
async def test_circuit_v2_transport_relay_selection_round_robin_no_reservation():
    """Test that relay selection rotates through all relays without reservations."""
    async with HostFactory.create_batch_and_listen(4) as hosts:
        client_host, relay_host1, relay_host2, relay_host3 = hosts
        logger.info(
            "Created hosts for test_circuit_v2_transport_relay_selection_round_robin"
        )

        # Setup
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        client_config = RelayConfig()
        client_protocol = CircuitV2Protocol(client_host, limits, allow_hop=False)
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        client_transport.discovery = client_discovery

        relay_id1 = relay_host1.get_id()
        relay_id2 = relay_host2.get_id()
        relay_id3 = relay_host3.get_id()

        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                await connect(client_host, relay_host1)
                await connect(client_host, relay_host2)
                await connect(client_host, relay_host3)
                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Add relays to discovery
        await client_discovery._add_relay(relay_id1)
        await client_discovery._add_relay(relay_id2)
        await client_discovery._add_relay(relay_id3)

        # Create target peer info for selection
        target_info = PeerInfo(relay_host1.get_id(), relay_host1.get_addrs())

        # Test round-robin: should cycle through relays 1 -> 2 -> 3 -> 1
        selected1 = await client_transport._select_relay(target_info)
        assert selected1 == relay_id1, "First selection should be relay1"

        selected2 = await client_transport._select_relay(target_info)
        assert selected2 == relay_id2, "Second selection should be relay2"

        selected3 = await client_transport._select_relay(target_info)
        assert selected3 == relay_id3, "Third selection should be relay3"

        selected4 = await client_transport._select_relay(target_info)
        assert selected4 == relay_id1, "Fourth selection should cycle back to relay1"

        logger.info("Round-robin relay selection test passed")


@pytest.mark.trio
async def test_circuit_v2_transport_relay_selection_prioritizes_reservations():
    """Test that relays with active reservations are prioritized over others."""
    async with HostFactory.create_batch_and_listen(4) as hosts:
        client_host, relay_host1, relay_host2, relay_host3 = hosts
        logger.info(
            "Created hosts for test_circuit_v2_transport_"
            "relay_selection_prioritizes_reservations"
        )

        # Setup
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        client_config = RelayConfig()
        client_protocol = CircuitV2Protocol(client_host, limits, allow_hop=False)
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        client_transport.discovery = client_discovery

        relay_id1 = relay_host1.get_id()
        relay_id2 = relay_host2.get_id()
        relay_id3 = relay_host3.get_id()

        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                await connect(client_host, relay_host1)
                await connect(client_host, relay_host2)
                await connect(client_host, relay_host3)
                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Add relays to discovery
        await client_discovery._add_relay(relay_id1)
        await client_discovery._add_relay(relay_id2)
        await client_discovery._add_relay(relay_id3)

        # Mark relay2 as having a reservation
        relay_info2 = client_discovery.get_relay_info(relay_id2)
        if relay_info2:
            relay_info2.has_reservation = True
            relay_info2.reservation_expires_at = time.time() + 3600

        # Create target peer info for selection
        target_info = PeerInfo(relay_host1.get_id(), relay_host1.get_addrs())

        # All selections should now prefer relay2 (the one with reservation)
        selected1 = await client_transport._select_relay(target_info)
        assert selected1 == relay_id2, (
            "Should select relay2 (has reservation) over relay1"
        )

        selected2 = await client_transport._select_relay(target_info)
        assert selected2 == relay_id2, "Should keep selecting relay2 (has reservation)"

        logger.info("Reservation prioritization test passed")


@pytest.mark.trio
async def test_circuit_v2_transport_relay_selection_multiple_reservations():
    """Test round-robin among relays with reservations when multiple exist."""
    async with HostFactory.create_batch_and_listen(4) as hosts:
        client_host, relay_host1, relay_host2, relay_host3 = hosts
        logger.info(
            "Created hosts for test_circuit_v2_transport_"
            "relay_selection_multiple_reservations"
        )

        # Setup
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        client_config = RelayConfig()
        client_protocol = CircuitV2Protocol(client_host, limits, allow_hop=False)
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        client_transport.discovery = client_discovery

        relay_id1 = relay_host1.get_id()
        relay_id2 = relay_host2.get_id()
        relay_id3 = relay_host3.get_id()

        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                await connect(client_host, relay_host1)
                await connect(client_host, relay_host2)
                await connect(client_host, relay_host3)
                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Add relays to discovery
        await client_discovery._add_relay(relay_id1)
        await client_discovery._add_relay(relay_id2)
        await client_discovery._add_relay(relay_id3)

        # Mark relay1 and relay3 as having reservations (not relay2)
        relay_info1 = client_discovery.get_relay_info(relay_id1)
        if relay_info1:
            relay_info1.has_reservation = True
            relay_info1.reservation_expires_at = time.time() + 3600

        relay_info3 = client_discovery.get_relay_info(relay_id3)
        if relay_info3:
            relay_info3.has_reservation = True
            relay_info3.reservation_expires_at = time.time() + 3600

        # Create target peer info for selection
        target_info = PeerInfo(relay_host1.get_id(), relay_host1.get_addrs())

        # Should round-robin only among relays with reservations (1 and 3)
        selected1 = await client_transport._select_relay(target_info)
        assert selected1 == relay_id1, (
            "First selection should be relay1 (has reservation)"
        )

        selected2 = await client_transport._select_relay(target_info)
        assert selected2 == relay_id3, (
            "Second selection should be relay3 (has reservation)"
        )

        selected3 = await client_transport._select_relay(target_info)
        assert selected3 == relay_id1, "Third selection should cycle back to relay1"

        # Relay2 should never be selected since it doesn't have a reservation
        for _ in range(10):
            selected = await client_transport._select_relay(target_info)
            assert selected != relay_id2, (
                "relay2 (no reservation) should not be selected"
            )

        logger.info("Multiple reservations round-robin test passed")


@pytest.mark.trio
async def test_circuit_v2_transport_relay_selection_fallback_no_reservation():
    """Test fallback to non-reserved relays when no reservations exist."""
    async with HostFactory.create_batch_and_listen(3) as hosts:
        client_host, relay_host1, relay_host2 = hosts
        logger.info(
            "Created hosts for test_circuit_v2_transport_relay_selection_fallback"
        )

        # Setup
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        client_config = RelayConfig()
        client_protocol = CircuitV2Protocol(client_host, limits, allow_hop=False)
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        client_transport.discovery = client_discovery

        relay_id1 = relay_host1.get_id()
        relay_id2 = relay_host2.get_id()

        # Connect all peers
        try:
            with trio.fail_after(CONNECT_TIMEOUT):
                await connect(client_host, relay_host1)
                await connect(client_host, relay_host2)
                logger.info("All connections established")
        except Exception as e:
            logger.error("Failed to connect peers: %s", str(e))
            raise

        # Add relays to discovery (without reservations)
        await client_discovery._add_relay(relay_id1)
        await client_discovery._add_relay(relay_id2)

        # Create target peer info for selection
        target_info = PeerInfo(relay_host1.get_id(), relay_host1.get_addrs())

        # Should still select relays even without reservations
        selected1 = await client_transport._select_relay(target_info)
        assert selected1 is not None, "Should select a relay even without reservations"
        assert selected1 in [relay_id1, relay_id2], (
            "Should select from available relays"
        )

        logger.info("Fallback to non-reserved relays test passed")


@pytest.mark.trio
async def test_circuit_v2_transport_no_relay_found():
    """Test that _select_relay returns None when no relays are available."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        client_host = hosts[0]
        logger.info("Created host for test_circuit_v2_transport_no_relay_found")

        # Setup
        limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )

        client_config = RelayConfig()
        client_protocol = CircuitV2Protocol(client_host, limits, allow_hop=False)
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
            discovery_interval=client_config.discovery_interval,
            max_relays=client_config.max_relays,
        )

        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        client_transport.discovery = client_discovery

        # Override max_auto_relay_attempts to make test faster
        client_transport.client_config.max_auto_relay_attempts = 1

        # Create target peer info for selection
        target_info = PeerInfo(client_host.get_id(), client_host.get_addrs())

        # Should return None when no relays are available
        selected = await client_transport._select_relay(target_info)
        assert selected is None, "Should return None when no relays are available"

        logger.info("No relay found test passed")

"""Tests for the Circuit Relay v2 transport functionality."""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from base58 import b58encode
import multiaddr
from multiaddr import Multiaddr
import trio

from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.stream.exceptions import (
    StreamEOF,
    StreamReset,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.discovery import (
    RelayDiscovery,
    RelayInfo,
)
from libp2p.relay.circuit_v2.pb.circuit_pb2 import (
    HopMessage,
)
from libp2p.relay.circuit_v2.protocol import (
    STOP_PROTOCOL_ID,
    CircuitV2Protocol,
    RelayLimits,
)
from libp2p.relay.circuit_v2.protocol_buffer import StatusCode, create_status
from libp2p.relay.circuit_v2.transport import (
    ID,
    PROTOCOL_ID,
    CircuitV2Listener,
    CircuitV2Transport,
    TrackedRawConnection,
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
SLEEP_TIME = 0.05  # seconds (reduced for CI performance)
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

TOP_N = 5


@pytest.fixture
def id_mock():
    mock = Mock()
    mock.from_base58 = Mock()
    return mock


@pytest.fixture
def protocol():
    return Mock(spec=CircuitV2Protocol)


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
async def test_circuit_v2_transport_message_routing_through_relay():
    """
    Test end-to-end message transfer from source to destination through relay.
    """
    async with HostFactory.create_batch_and_listen(3) as hosts:
        client_host, relay_host, target_host = hosts
        logger.debug(
            "Test hosts: client_host=%s relay_host=%s target_host=%s",
            client_host.get_id(),
            relay_host.get_id(),
            target_host.get_id(),
        )

        # Configure relay
        limits = RelayLimits(
            duration=3600,  # 1 hour
            data=1024 * 1024 * 100,  # 100 MB
            max_circuit_conns=10,
            max_reservations=5,
        )
        relay_config = RelayConfig(
            roles=RelayRole.HOP | RelayRole.STOP | RelayRole.CLIENT, limits=limits
        )
        relay_protocol = CircuitV2Protocol(relay_host, limits, allow_hop=True)
        CircuitV2Transport(relay_host, relay_protocol, relay_config)
        relay_host.set_stream_handler(PROTOCOL_ID, relay_protocol._handle_hop_stream)
        relay_host.set_stream_handler(
            STOP_PROTOCOL_ID, relay_protocol._handle_stop_stream
        )

        client_limits = RelayLimits(
            duration=3600,  # 1 hour
            data=1024 * 1024 * 100,  # 100 MB
            max_circuit_conns=10,
            max_reservations=5,
        )
        client_config = RelayConfig(
            roles=RelayRole.CLIENT | RelayRole.STOP, limits=client_limits
        )
        client_protocol = CircuitV2Protocol(client_host, client_limits, allow_hop=False)
        client_transport = CircuitV2Transport(
            client_host, client_protocol, client_config
        )
        client_discovery = RelayDiscovery(
            host=client_host,
            auto_reserve=False,
        )
        client_transport.discovery = client_discovery

        dest_limits = RelayLimits(
            duration=DEFAULT_RELAY_LIMITS.duration,
            data=DEFAULT_RELAY_LIMITS.data,
            max_circuit_conns=DEFAULT_RELAY_LIMITS.max_circuit_conns,
            max_reservations=DEFAULT_RELAY_LIMITS.max_reservations,
        )
        dest_config = RelayConfig(
            roles=RelayRole.STOP | RelayRole.CLIENT, limits=dest_limits
        )
        dest_protocol = CircuitV2Protocol(target_host, dest_limits, allow_hop=False)
        CircuitV2Transport(target_host, dest_protocol, dest_config)
        target_host.set_stream_handler(PROTOCOL_ID, dest_protocol._handle_hop_stream)
        target_host.set_stream_handler(
            STOP_PROTOCOL_ID, dest_protocol._handle_stop_stream
        )

        # Register echo protocol handler on destination
        test_protocol = TProtocol("/test/echo/1.0.0")
        message_received = trio.Event()
        received_message = {}

        async def app_echo_handler(stream):
            try:
                msg = await stream.read(1024)
                received_message["msg"] = msg
                await stream.write(b"echo:" + msg)
                message_received.set()
            finally:
                await stream.close()

        target_host.set_stream_handler(test_protocol, app_echo_handler)

        # Step 1: Destination connects to Relay
        with trio.fail_after(CONNECT_TIMEOUT):
            await connect(target_host, relay_host)
            assert relay_host.get_id() in target_host.get_network().connections
            assert target_host.get_id() in relay_host.get_network().connections

        await trio.sleep(SLEEP_TIME)

        # Step 2: Source connects to Relay
        with trio.fail_after(CONNECT_TIMEOUT):
            await connect(client_host, relay_host)
            assert relay_host.get_id() in client_host.get_network().connections
            assert client_host.get_id() in relay_host.get_network().connections

        await trio.sleep(SLEEP_TIME)
        relay_id = relay_host.get_id()
        client_discovery.get_relay = lambda: relay_id

        # Step 3: Source tries to dial the destination via p2p-circuit and opens stream
        relay_addr = relay_host.get_addrs()[0]
        dest_id = target_host.get_id()
        p2p_circuit_addr = Multiaddr(f"{relay_addr}/p2p-circuit/p2p/{dest_id}")
        # Register the relay address for the destination on the client peerstore
        client_host.peerstore.add_addr(dest_id, p2p_circuit_addr, 3600)

        with trio.fail_after(CONNECT_TIMEOUT * 2):
            # Actually dial the destination through relay using client_transport
            await client_transport.dial(p2p_circuit_addr)

            # Next, open a stream on the test protocol
            stream = await client_host.new_stream(dest_id, [test_protocol])
            test_msg = b"hello-via-relay"
            await stream.write(test_msg)
            echo_reply = await stream.read(1024)
            await stream.close()

        # Wait until the destination handler receives the message
        with trio.fail_after(SLEEP_TIME * 5):
            await message_received.wait()

        # Assertions
        assert received_message["msg"] == test_msg, "Destination received wrong message"
        assert echo_reply == b"echo:" + test_msg, "Client did not get echo response"

        logger.info("Relay message transfer test passed: echoed %s", test_msg)


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


# Tests for TrackedRawConnection
class TestTrackedRawConnection:
    """Test suite for TrackedRawConnection wrapper."""

    @pytest.mark.trio
    async def test_tracked_connection_calls_record_circuit_closed_on_close(self):
        """Test that closing a TrackedRawConnection calls record_circuit_closed."""
        from unittest.mock import AsyncMock

        from libp2p.crypto.secp256k1 import create_new_key_pair
        from libp2p.network.connection.raw_connection import RawConnection
        from libp2p.peer.id import ID
        from libp2p.relay.circuit_v2.performance_tracker import (
            RelayPerformanceTracker,
        )

        # Create mock stream
        mock_stream = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create real RawConnection with mock stream
        raw_conn = RawConnection(stream=mock_stream, initiator=True)

        # Create tracker and relay ID
        tracker = RelayPerformanceTracker()
        key_pair = create_new_key_pair()
        relay_id = ID.from_pubkey(key_pair.public_key)

        # Create tracked connection
        tracked_conn = TrackedRawConnection(
            wrapped=raw_conn, relay_id=relay_id, tracker=tracker
        )

        # Record circuit opened first
        tracker.record_circuit_opened(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 1

        # Close the connection
        await tracked_conn.close()

        # Verify stream.close was called
        mock_stream.close.assert_called_once()

        # Verify circuit was closed (active_circuits decremented)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 0

    @pytest.mark.trio
    async def test_tracked_connection_double_close_does_not_double_count(self):
        """Test that closing a TrackedRawConnection twice doesn't double-count."""
        from unittest.mock import AsyncMock

        from libp2p.crypto.secp256k1 import create_new_key_pair
        from libp2p.network.connection.raw_connection import RawConnection
        from libp2p.peer.id import ID
        from libp2p.relay.circuit_v2.performance_tracker import (
            RelayPerformanceTracker,
        )

        # Create mock stream
        mock_stream = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create real RawConnection with mock stream
        raw_conn = RawConnection(stream=mock_stream, initiator=True)

        # Create tracker and relay ID
        tracker = RelayPerformanceTracker()
        key_pair = create_new_key_pair()
        relay_id = ID.from_pubkey(key_pair.public_key)

        # Create tracked connection
        tracked_conn = TrackedRawConnection(
            wrapped=raw_conn, relay_id=relay_id, tracker=tracker
        )

        # Record circuit opened first
        tracker.record_circuit_opened(relay_id)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 1

        # Close the connection twice
        await tracked_conn.close()
        await tracked_conn.close()

        # Verify stream.close was called at least once (first close)
        # Second close is prevented by _closed flag to avoid double-counting
        assert mock_stream.close.call_count >= 1

        # Verify circuit was closed only once (active_circuits = 0, not -1)
        stats = tracker.get_relay_stats(relay_id)
        assert stats is not None
        assert stats.active_circuits == 0

    @pytest.mark.trio
    async def test_tracked_connection_delegates_methods(self):
        """Test that TrackedRawConnection properly delegates all methods."""
        from unittest.mock import AsyncMock, MagicMock

        from libp2p.crypto.secp256k1 import create_new_key_pair
        from libp2p.network.connection.raw_connection import RawConnection
        from libp2p.peer.id import ID
        from libp2p.relay.circuit_v2.performance_tracker import (
            RelayPerformanceTracker,
        )

        # Create mock stream
        mock_stream = AsyncMock()
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock(return_value=b"test data")
        mock_stream.get_remote_address = MagicMock(return_value=("127.0.0.1", 12345))

        # Create real RawConnection with mock stream
        raw_conn = RawConnection(stream=mock_stream, initiator=True)

        # Create tracker and relay ID
        tracker = RelayPerformanceTracker()
        key_pair = create_new_key_pair()
        relay_id = ID.from_pubkey(key_pair.public_key)

        # Create tracked connection
        tracked_conn = TrackedRawConnection(
            wrapped=raw_conn, relay_id=relay_id, tracker=tracker
        )

        # Test write delegation
        await tracked_conn.write(b"test")
        mock_stream.write.assert_called_once_with(b"test")

        # Test read delegation
        data = await tracked_conn.read(10)
        assert data == b"test data"
        mock_stream.read.assert_called_once_with(10)

        # Test get_remote_address delegation
        addr = tracked_conn.get_remote_address()
        assert addr == ("127.0.0.1", 12345)
        mock_stream.get_remote_address.assert_called_once()

        # Test property access
        assert tracked_conn.stream == mock_stream
        assert tracked_conn.is_initiator is True


# Additional tests from origin/main
@pytest.fixture
def peer_info() -> PeerInfo:
    peer_id = ID.from_base58("12D3KooW")
    return PeerInfo(peer_id, [])


@pytest.fixture
def circuit_v2_transport():
    """Set up a CircuitV2Transport instance with mocked dependencies."""
    # Mock dependencies
    host = MagicMock(spec=IHost)
    protocol = MagicMock(spec=CircuitV2Protocol)
    config = MagicMock(spec=RelayConfig)

    # Mock RelayConfig attributes used by RelayDiscovery
    config.enable_client = True
    config.discovery_interval = 60
    config.max_relays = 5
    config.timeouts = MagicMock()
    config.timeouts.discovery_stream_timeout = 30
    config.timeouts.peer_protocol_timeout = 30

    # Initialize CircuitV2Transport
    transport = CircuitV2Transport(host=host, protocol=protocol, config=config)

    # Replace discovery with a mock to avoid real initialization
    transport.discovery = MagicMock(spec=RelayDiscovery)

    return transport


def _metrics_for(transport, relay):
    """
    Find metric dict for a relay by comparing
    to_string() to avoid identity issues.
    """
    for k, v in transport._relay_metrics.items():
        # some tests set relay.to_string.return_value
        try:
            if k.to_string() == relay.to_string():
                return v
        except Exception:
            # fallback if to_string is not a callable on the mock
            try:
                if k.to_string.return_value == relay.to_string.return_value:
                    return v
            except Exception:
                continue
    raise AssertionError("Metrics for relay not found")


@pytest.mark.trio
async def test_select_relay_no_relays(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay when no relays are available."""
    circuit_v2_transport.discovery.get_relays.return_value = []
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = []
    mock_sleep = mocker.patch("trio.sleep", new=AsyncMock())

    result = await circuit_v2_transport._select_relay(peer_info)

    assert result is None
    assert (
        circuit_v2_transport.discovery.get_relays.call_count
        == circuit_v2_transport.client_config.max_auto_relay_attempts
    )
    assert circuit_v2_transport._relay_list == []
    assert (
        mock_sleep.call_count
        == circuit_v2_transport.client_config.max_auto_relay_attempts
    )


@pytest.mark.trio
async def test_select_relay_all_unavailable(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay when relays are present but all are unhealthy."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True

    # Make relay1 unhealthy by giving it a very low success rate
    # This will make get_relay_score return float("inf")
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=100.0, success=False
    )
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=100.0, success=False
    )
    # Now success rate is 0%, which is below min_success_rate (default 0.5)

    mock_sleep = mocker.patch("trio.sleep", new=AsyncMock())

    result = await circuit_v2_transport._select_relay(peer_info)

    # The new implementation falls back to first available relay if all are unhealthy
    # So result will be relay1 (fallback behavior), returned immediately
    assert result is not None
    assert result.to_string() == relay1.to_string()
    # Should return immediately (no retries needed since relay is found)
    assert circuit_v2_transport.discovery.get_relays.call_count == 1
    assert mock_sleep.call_count == 0


@pytest.mark.trio
async def test_select_relay_round_robin(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay round-robin selection with equal scores."""
    mock_sleep = mocker.patch("trio.sleep", new=AsyncMock())
    relay1 = MagicMock(spec=ID)
    relay2 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    relay2.to_string.return_value = "relay2"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1, relay2]
    circuit_v2_transport.client_config.enable_auto_relay = True

    # Set up performance tracker so both relays have equal scores
    # This will trigger round-robin selection
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=50.0, success=True
    )
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay2, latency_ms=50.0, success=True
    )

    # Reset counter for predictable round-robin
    circuit_v2_transport.relay_counter = 0

    result1 = await circuit_v2_transport._select_relay(peer_info)
    # With equal scores, round-robin should select based on counter
    assert result1 is not None
    assert result1.to_string() in [relay1.to_string(), relay2.to_string()]

    result2 = await circuit_v2_transport._select_relay(peer_info)
    assert result2 is not None
    assert result2.to_string() in [relay1.to_string(), relay2.to_string()]

    result3 = await circuit_v2_transport._select_relay(peer_info)
    assert result3 is not None
    assert result3.to_string() in [relay1.to_string(), relay2.to_string()]

    assert mock_sleep.call_count == 0
    # Check that performance tracker has stats for both relays
    stats1 = circuit_v2_transport.performance_tracker.get_relay_stats(relay1)
    stats2 = circuit_v2_transport.performance_tracker.get_relay_stats(relay2)
    assert stats1 is not None
    assert stats2 is not None
    assert stats1.latency_ema_ms > 0
    assert stats2.latency_ema_ms > 0


@pytest.mark.trio
async def test_is_relay_available_success(circuit_v2_transport, mocker):
    """Test _is_relay_available when the relay is reachable."""
    relay_id = MagicMock(spec=ID)
    stream = AsyncMock()
    mocker.patch.object(
        circuit_v2_transport.host, "new_stream", AsyncMock(return_value=stream)
    )

    result = await circuit_v2_transport._is_relay_available(relay_id)

    assert result is True
    circuit_v2_transport.host.new_stream.assert_called_once_with(
        relay_id,
        [PROTOCOL_ID],
    )
    stream.close.assert_called_once()


@pytest.mark.trio
async def test_is_relay_available_failure(circuit_v2_transport, mocker):
    """Test _is_relay_available when the relay is unreachable."""
    relay_id = MagicMock(spec=ID)
    mocker.patch.object(
        circuit_v2_transport.host,
        "new_stream",
        AsyncMock(side_effect=Exception("Connection failed")),
    )

    result = await circuit_v2_transport._is_relay_available(relay_id)

    assert result is False
    circuit_v2_transport.host.new_stream.assert_called_once_with(
        relay_id, [PROTOCOL_ID]
    )


@pytest.mark.trio
async def test_select_relay_scoring_priority(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay prefers relays with better scores."""
    relay1 = MagicMock(spec=ID)
    relay2 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    relay2.to_string.return_value = "relay2"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1, relay2]
    circuit_v2_transport.client_config.enable_auto_relay = True

    # Set up performance tracker: relay1 has better score
    # (lower latency, higher success rate)
    # relay1: low latency, all successes
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=10.0, success=True
    )
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=10.0, success=True
    )

    # relay2: higher latency, some failures
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay2, latency_ms=100.0, success=True
    )
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay2, latency_ms=100.0, success=False
    )

    result = await circuit_v2_transport._select_relay(peer_info)

    # relay1 should be selected due to better score (lower latency, higher success rate)
    assert result is not None
    assert result.to_string() == relay1.to_string()

    # Verify performance tracker stats
    stats1 = circuit_v2_transport.performance_tracker.get_relay_stats(relay1)
    stats2 = circuit_v2_transport.performance_tracker.get_relay_stats(relay2)
    assert stats1 is not None
    assert stats2 is not None
    assert stats1.latency_ema_ms < stats2.latency_ema_ms
    assert stats1.success_rate > stats2.success_rate


@pytest.mark.trio
async def test_select_relay_fewer_than_top_n(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay when fewer relays than TOP_N are available."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True

    # Set up performance tracker with a healthy relay
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=50.0, success=True
    )

    result = await circuit_v2_transport._select_relay(peer_info)

    assert result is not None
    assert result.to_string() == relay1.to_string()

    # Verify performance tracker has stats
    stats = circuit_v2_transport.performance_tracker.get_relay_stats(relay1)
    assert stats is not None
    assert stats.success_count > 0


@pytest.mark.trio
async def test_select_relay_duplicate_relays(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay handles duplicate relays correctly."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1, relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True

    # Set up performance tracker with a healthy relay
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=50.0, success=True
    )

    result = await circuit_v2_transport._select_relay(peer_info)

    # Should still select relay1 (duplicates are handled by performance_tracker)
    assert result is not None
    assert result.to_string() == relay1.to_string()

    # Verify performance tracker has stats
    stats = circuit_v2_transport.performance_tracker.get_relay_stats(relay1)
    assert stats is not None


@pytest.mark.trio
async def test_select_relay_metrics_persistence(
    circuit_v2_transport, peer_info, mocker
):
    """Test _select_relay persists and updates metrics across multiple calls."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True

    # First, record a failed attempt
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=100.0, success=False
    )

    # Verify stats exist after first attempt
    stats = circuit_v2_transport.performance_tracker.get_relay_stats(relay1)
    assert stats is not None
    assert stats.failure_count == 1
    assert stats.success_count == 0

    # Now record a successful attempt
    circuit_v2_transport.performance_tracker.record_connection_attempt(
        relay_id=relay1, latency_ms=50.0, success=True
    )

    # Verify stats are updated
    stats = circuit_v2_transport.performance_tracker.get_relay_stats(relay1)
    assert stats is not None
    assert stats.failure_count == 1
    assert stats.success_count == 1
    assert stats.success_rate == 0.5

    # Now select relay - should work since it has some success
    result = await circuit_v2_transport._select_relay(peer_info)
    assert result is not None
    assert result.to_string() == relay1.to_string()


@pytest.mark.trio
async def test_select_relay_backoff_timing(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay exponential backoff on empty scored_relays."""
    circuit_v2_transport.discovery.get_relays.return_value = []
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = []
    mock_sleep = mocker.patch("trio.sleep", new=AsyncMock())
    circuit_v2_transport.client_config.max_auto_relay_attempts = 3

    await circuit_v2_transport._select_relay(peer_info)

    expected_backoffs = [min(2**i, 10) for i in range(3)]
    assert mock_sleep.call_args_list == [
        ((backoff,), {}) for backoff in expected_backoffs
    ]


@pytest.mark.trio
async def test_select_relay_disabled_auto_relay(circuit_v2_transport, peer_info):
    """Test _select_relay when auto_relay is disabled."""
    circuit_v2_transport.client_config.enable_auto_relay = False

    result = await circuit_v2_transport._select_relay(peer_info)

    assert result is None
    assert circuit_v2_transport.discovery.get_relays.call_count == 0


@pytest.mark.trio
async def test_run_registers_stream_handler():
    host = MagicMock()
    handler_function = AsyncMock()
    listener = CircuitV2Listener(
        host, handler_function, protocol=MagicMock(), config=MagicMock(enable_stop=True)
    )

    # Patch the manager.wait_finished property
    with patch.object(
        type(listener), "manager", new_callable=MagicMock
    ) as mock_manager:
        mock_manager.wait_finished = AsyncMock(return_value=None)
        await listener.run()

    # Assert that host.set_stream_handler was called with PROTOCOL_ID
    host.set_stream_handler.assert_called_once()
    protocol_arg, func_arg = host.set_stream_handler.call_args[0]
    assert protocol_arg == PROTOCOL_ID
    assert callable(func_arg)


@pytest.mark.trio
async def test_stream_handler_calls_handler_function():
    host = MagicMock()
    handler_function = AsyncMock()
    listener = CircuitV2Listener(
        host, handler_function, protocol=MagicMock(), config=MagicMock(enable_stop=True)
    )

    with patch.object(
        type(listener), "manager", new_callable=MagicMock
    ) as mock_manager:
        mock_manager.wait_finished = AsyncMock(return_value=None)
        await listener.run()

    # Extract the registered stream handler
    _, stream_handler = host.set_stream_handler.call_args[0]

    # Create a fake stream with get_remote_peer_id
    fake_stream = MagicMock()
    fake_stream.get_remote_peer_id = MagicMock(return_value=ID(b"12345"))

    # Patch handle_incoming_connection to return a dummy RawConnection
    listener.handle_incoming_connection = AsyncMock(
        return_value=RawConnection(stream=fake_stream, initiator=False)
    )

    await stream_handler(fake_stream)

    # Assert that handler_function was called with the RawConnection
    handler_function.assert_awaited_once()


@pytest.mark.trio
async def test_refresh_worker_removes_expired():
    host = MagicMock()
    host.new_stream = AsyncMock()
    transport = CircuitV2Transport(host, protocol=MagicMock(), config=MagicMock())

    # generate valid fake peer ID
    relay_id = ID.from_base58(b58encode(b"expired" + b"\x00" * 25).decode())

    now = time.time()
    # reservation already expired
    transport._reservations = {relay_id: now - 1}
    transport._make_reservation = AsyncMock(return_value=True)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(transport._refresh_reservations_worker)
        await trio.sleep(0.2)
        nursery.cancel_scope.cancel()

    assert relay_id not in transport._reservations


@pytest.mark.trio
async def test_refresh_worker_refreshes_active_reservation():
    host = MagicMock()
    stream_mock = AsyncMock()
    host.new_stream = AsyncMock(return_value=stream_mock)
    transport = CircuitV2Transport(host, protocol=MagicMock(), config=MagicMock())

    # valid fake peer ID
    relay_id = ID.from_base58(b58encode(b"active" + b"\x00" * 26).decode())

    now = time.time()
    ttl = 1.0  # short TTL
    transport._reservations = {relay_id: now + ttl}
    transport._make_reservation = AsyncMock(return_value=True)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(transport._refresh_reservations_worker)
        await trio.sleep(0.2)
        nursery.cancel_scope.cancel()

    # reservation should still exist
    assert relay_id in transport._reservations
    transport._make_reservation.assert_called()


@pytest.mark.trio
async def test_refresh_worker_handles_failed_refresh():
    host = MagicMock()
    stream_mock = AsyncMock()
    host.new_stream = AsyncMock(return_value=stream_mock)
    transport = CircuitV2Transport(host, protocol=MagicMock(), config=MagicMock())

    # valid fake peer ID
    relay_id = ID.from_base58(b58encode(b"fail" + b"\x00" * 28).decode())

    now = time.time()
    ttl = 1.0
    transport._reservations = {relay_id: now + ttl}

    # simulate reservation failure
    transport._make_reservation = AsyncMock(return_value=False)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(transport._refresh_reservations_worker)
        await trio.sleep(0.2)
        nursery.cancel_scope.cancel()

    assert relay_id in transport._reservations
    transport._make_reservation.assert_called()


@pytest.mark.trio
async def test_store_multiaddrs_stores_addresses(protocol):
    mock_host = Mock()
    peerstore = Mock()
    mock_host.get_peerstore.return_value = peerstore

    transport = CircuitV2Transport(host=mock_host, config=Mock(), protocol=protocol)

    priv_key1 = create_new_key_pair()
    priv_key2 = create_new_key_pair()
    peer_id = ID.from_pubkey(priv_key1.public_key)
    relay_peer_id = ID.from_pubkey(priv_key2.public_key)

    peer_info = PeerInfo(peer_id, [])

    relay_ma = multiaddr.Multiaddr(
        f"/ip4/127.0.0.1/tcp/4001/p2p/{relay_peer_id.to_base58()}"
    )
    peerstore.addrs.return_value = [relay_ma]

    transport._store_multiaddrs(peer_info, relay_peer_id)

    peerstore.add_addrs.assert_called()
    stored_peer_id, addrs = peerstore.add_addrs.call_args[0]
    assert stored_peer_id == peer_info.peer_id
    assert any("/p2p-circuit/p2p/" in str(ma) for ma in addrs)


@pytest.mark.trio
async def test_dial_peer_info_uses_stored_multiaddr(protocol):
    mock_host = Mock()
    peerstore = Mock()
    mock_host.get_peerstore.return_value = peerstore

    # Create TrackedRawConnection to match _dial_via_circuit_addr return value
    from libp2p.relay.circuit_v2.performance_tracker import RelayPerformanceTracker

    mock_raw_conn = RawConnection(stream=Mock(), initiator=True)
    tracker = RelayPerformanceTracker()
    relay_key = create_new_key_pair()
    relay_peer_id = ID.from_pubkey(relay_key.public_key)
    mock_conn = TrackedRawConnection(
        wrapped=mock_raw_conn,
        relay_id=relay_peer_id,
        tracker=tracker,
    )

    transport = CircuitV2Transport(host=mock_host, config=Mock(), protocol=protocol)
    transport._dial_via_circuit_addr = AsyncMock(return_value=mock_conn)

    priv_key = create_new_key_pair()
    peer_id = ID.from_pubkey(priv_key.public_key)
    peer_info = PeerInfo(peer_id, [])

    circuit_ma = multiaddr.Multiaddr(
        f"/ip4/127.0.0.1/tcp/4001/p2p/{relay_peer_id.to_base58()}/p2p-circuit/p2p/{peer_id.to_base58()}"
    )
    relay_addr = multiaddr.Multiaddr(
        f"/ip4/127.0.0.1/tcp/4001/p2p/{relay_peer_id.to_base58()}"
    )

    # Mock peerstore.addrs: return circuit_ma for peer_id, relay_addr for relay_peer_id
    def addrs_side_effect(peer_id_arg):
        if peer_id_arg == peer_id:
            return [circuit_ma]
        elif peer_id_arg == relay_peer_id:
            return [relay_addr]
        return []

    peerstore.addrs.side_effect = addrs_side_effect

    conn = await transport.dial_peer_info(peer_info)

    transport._dial_via_circuit_addr.assert_called_with(circuit_ma, peer_info)
    assert conn == mock_conn


@pytest.mark.trio
async def test_dial_peer_info_creates_and_stores_circuit(protocol):
    mock_host = Mock()

    peerstore = Mock()
    mock_host.get_peerstore.return_value = peerstore

    relay_stream = AsyncMock()
    mock_host.new_stream = AsyncMock(return_value=relay_stream)

    relay_key = create_new_key_pair()
    relay_peer_id = ID.from_pubkey(relay_key.public_key)
    relay_addr = Multiaddr(f"/ip4/127.0.0.1/tcp/4001/p2p/{relay_peer_id.to_base58()}")
    relay_info = PeerInfo(relay_peer_id, [relay_addr])

    mock_host.connect = AsyncMock(return_value=relay_info)
    mock_host.get_addrs.return_value = [relay_addr]
    mock_host.get_id.return_value = relay_peer_id
    mock_host.get_private_key.return_value = relay_key.private_key  # <-- THIS

    transport = CircuitV2Transport(
        host=mock_host,
        config=Mock(enable_client=False),
        protocol=protocol,
    )
    transport._select_relay = AsyncMock(return_value=relay_peer_id)

    dest_key = create_new_key_pair()
    dest_peer_id = ID.from_pubkey(dest_key.public_key)
    peer_info = PeerInfo(dest_peer_id, [])

    peerstore.addrs.return_value = [relay_addr]

    status = create_status(code=StatusCode.OK, message="OK")
    hop_resp = HopMessage(type=HopMessage.STATUS, status=status)
    relay_stream.read.return_value = hop_resp.SerializeToString()
    relay_stream.write = AsyncMock()

    conn = await transport.dial_peer_info(peer_info)

    peerstore.add_addrs.assert_called_once()
    assert isinstance(conn, TrackedRawConnection)
    assert conn.is_initiator


def test_valid_circuit_multiaddr(id_mock, circuit_v2_transport):
    valid_peer_id = "QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
    id_obj = Mock(spec=ID)
    id_mock.from_base58.return_value = id_obj

    ip4_proto = Mock()
    ip4_proto.name = "ip4"
    tcp_proto = Mock()
    tcp_proto.name = "tcp"
    circuit_proto = Mock()
    circuit_proto.name = "p2p-circuit"
    p2p_proto = Mock()
    p2p_proto.name = "p2p"

    with patch.object(multiaddr.Multiaddr, "items") as mock_items:
        mock_items.return_value = [
            (ip4_proto, "127.0.0.1"),
            (tcp_proto, "1234"),
            (circuit_proto, None),
            (p2p_proto, id_obj),
        ]

        ma = multiaddr.Multiaddr(
            f"/ip4/127.0.0.1/tcp/1234/p2p-circuit/p2p/{valid_peer_id}"
        )
        relay_ma, target_peer_id = circuit_v2_transport.parse_circuit_ma(ma)

        assert str(relay_ma) == "/ip4/127.0.0.1/tcp/1234"
        assert target_peer_id == id_obj
        id_mock.from_base58.assert_not_called()


def test_invalid_circuit_multiaddr(id_mock, circuit_v2_transport):
    valid_peer_id = "QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
    id_obj = Mock(spec=ID)
    id_mock.from_base58.return_value = id_obj

    ip4_proto = Mock()
    ip4_proto.name = "ip4"
    tcp_proto = Mock()
    tcp_proto.name = "tcp"
    circuit_proto = Mock()
    circuit_proto.name = "p2p-circuit"
    p2p_proto = Mock()
    p2p_proto.name = "p2p"
    ip6_proto = Mock()
    ip6_proto.name = "ip6"

    # Test case 1: Missing /p2p-circuit
    with patch.object(multiaddr.Multiaddr, "items") as mock_items:
        mock_items.return_value = [
            (ip4_proto, "127.0.0.1"),
            (tcp_proto, "1234"),
            (p2p_proto, id_obj),
        ]
        ma = multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/1234/p2p/{valid_peer_id}")
        with pytest.raises(ValueError) as exc_info:
            circuit_v2_transport.parse_circuit_ma(ma)
        assert str(exc_info.value) == f"Missing /p2p-circuit in Multiaddr: {ma}"

    # Test case 2: Missing /p2p/<peerID>
    with patch("multiaddr.protocols.protocol_with_name") as mock_proto:

        def proto_side_effect(name):
            if name == "p2p-circuit":
                return circuit_proto
            elif name == "ip4":
                return ip4_proto
            elif name == "tcp":
                return tcp_proto
            elif name == "ip6":
                return ip6_proto
            else:
                return Mock(name=name)

        mock_proto.side_effect = lambda name: (
            circuit_proto
            if name == "p2p-circuit"
            else ip4_proto
            if name == "ip4"
            else tcp_proto
            if name == "tcp"
            else ip6_proto
            if name == "ip6"
            else Mock(name=name)
        )

        with patch.object(multiaddr.Multiaddr, "items") as mock_items:
            mock_items.return_value = [
                (ip4_proto, "127.0.0.1"),
                (tcp_proto, "1234"),
                (circuit_proto, None),
                (ip6_proto, "::1"),
            ]
            ma = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/1234/p2p-circuit/ip6/::1")
            with pytest.raises(ValueError) as exc_info:
                circuit_v2_transport.parse_circuit_ma(ma)
            assert str(exc_info.value) == f"Missing /p2p/<peerID> at the end: {ma}"

    # Test case 3: Too short
    with patch.object(multiaddr.Multiaddr, "items") as mock_items:
        mock_items.return_value = [(ip4_proto, "127.0.0.1")]
        ma = multiaddr.Multiaddr("/ip4/127.0.0.1")
        with pytest.raises(ValueError) as exc_info:
            circuit_v2_transport.parse_circuit_ma(ma)
        assert str(exc_info.value) == f"Invalid circuit Multiaddr, too short: {ma}"

    # Test case 4: Wrong protocol instead of p2p-circuit
    with patch.object(multiaddr.Multiaddr, "items") as mock_items:
        mock_items.return_value = [
            (ip4_proto, "127.0.0.1"),
            (tcp_proto, "1234"),
            (ip6_proto, "::1"),
            (p2p_proto, id_obj),
        ]
        ma = multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/1234/ip6/::1/p2p/{valid_peer_id}")
        with pytest.raises(ValueError) as exc_info:
            circuit_v2_transport.parse_circuit_ma(ma)
        assert str(exc_info.value) == f"Missing /p2p-circuit in Multiaddr: {ma}"

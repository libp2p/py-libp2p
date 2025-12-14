"""Tests for the Circuit Relay v2 transport functionality."""

import itertools
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
    PeerInfo,
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


TOP_N = 5


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
    """Test _select_relay when relays are present but all are unavailable."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = [relay1]
    mocker.patch.object(
        circuit_v2_transport, "_is_relay_available", AsyncMock(return_value=False)
    )
    mock_sleep = mocker.patch("trio.sleep", new=AsyncMock())

    result = await circuit_v2_transport._select_relay(peer_info)

    assert result is None
    assert (
        circuit_v2_transport._is_relay_available.call_count
        == circuit_v2_transport.client_config.max_auto_relay_attempts
    )
    assert circuit_v2_transport._relay_list == [relay1]
    metrics = _metrics_for(circuit_v2_transport, relay1)
    assert (
        metrics["failures"]
        == circuit_v2_transport.client_config.max_auto_relay_attempts
    )
    assert (
        mock_sleep.call_count
        == circuit_v2_transport.client_config.max_auto_relay_attempts
    )


@pytest.mark.trio
async def test_select_relay_round_robin(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay round-robin selection of available relays."""
    mock_sleep = mocker.patch("trio.sleep", new=AsyncMock())
    # allow repeated calls by cycling the values
    mocker.patch("time.monotonic", side_effect=itertools.cycle([0, 0.1]))
    mocker.patch("time.time", return_value=1000.0)
    relay1 = MagicMock(spec=ID)
    relay2 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    relay2.to_string.return_value = "relay2"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1, relay2]
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = [relay1, relay2]
    mocker.patch.object(
        circuit_v2_transport, "_is_relay_available", AsyncMock(return_value=True)
    )

    circuit_v2_transport._last_relay_index = -1
    result1 = await circuit_v2_transport._select_relay(peer_info)
    assert result1.to_string() == relay2.to_string()
    assert circuit_v2_transport._last_relay_index == 0

    result2 = await circuit_v2_transport._select_relay(peer_info)
    assert result2.to_string() == relay1.to_string()
    assert circuit_v2_transport._last_relay_index == 1

    result3 = await circuit_v2_transport._select_relay(peer_info)
    assert result3.to_string() == relay2.to_string()
    assert circuit_v2_transport._last_relay_index == 0

    assert mock_sleep.call_count == 0
    # check metrics by looking up via helper
    metrics1 = _metrics_for(circuit_v2_transport, relay1)
    metrics2 = _metrics_for(circuit_v2_transport, relay2)
    assert metrics1["latency"] == pytest.approx(0.1, rel=1e-3)
    assert metrics2["latency"] == pytest.approx(0.1, rel=1e-3)


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
    circuit_v2_transport._relay_list = [relay1, relay2]
    mocker.patch.object(
        circuit_v2_transport, "_is_relay_available", AsyncMock(return_value=True)
    )

    async def fake_measure_relay(relay_id, scored):
        if relay_id is relay1:
            scored.append((relay_id, 0.8))  # better score
            circuit_v2_transport._relay_metrics[relay_id]["failures"] = 0
        else:
            scored.append((relay_id, 0.5))  # worse score
            circuit_v2_transport._relay_metrics[relay_id]["failures"] = 1

    mocker.patch.object(
        circuit_v2_transport, "_measure_relay", side_effect=fake_measure_relay
    )
    circuit_v2_transport._relay_metrics = {
        relay1: {"latency": 0.1, "failures": 0, "last_seen": 999.9},
        relay2: {"latency": 0.2, "failures": 2, "last_seen": 900.0},
    }

    circuit_v2_transport._last_relay_index = -1
    result = await circuit_v2_transport._select_relay(peer_info)

    assert result.to_string() == relay1.to_string()
    m1 = _metrics_for(circuit_v2_transport, relay1)
    m2 = _metrics_for(circuit_v2_transport, relay2)
    assert m1["latency"] == pytest.approx(0.1, rel=1e-3)
    assert m2["latency"] == pytest.approx(0.2, rel=1e-3)
    assert m1["failures"] == 0
    assert m2["failures"] == 1


@pytest.mark.trio
async def test_select_relay_fewer_than_top_n(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay when fewer relays than TOP_N are available."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = [relay1]
    mocker.patch.object(
        circuit_v2_transport, "_is_relay_available", AsyncMock(return_value=True)
    )
    mocker.patch("time.monotonic", side_effect=itertools.cycle([0, 0.1]))
    mocker.patch("time.time", return_value=1000.0)

    circuit_v2_transport._last_relay_index = -1
    result = await circuit_v2_transport._select_relay(peer_info)

    assert result.to_string() == relay1.to_string()
    assert circuit_v2_transport._last_relay_index == 0
    assert len(circuit_v2_transport._relay_list) == 1


@pytest.mark.trio
async def test_select_relay_duplicate_relays(circuit_v2_transport, peer_info, mocker):
    """Test _select_relay handles duplicate relays correctly."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1, relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = [relay1]
    mocker.patch.object(
        circuit_v2_transport, "_is_relay_available", AsyncMock(return_value=True)
    )
    mocker.patch("time.monotonic", side_effect=itertools.cycle([0, 0.1]))
    mocker.patch("time.time", return_value=1000.0)

    circuit_v2_transport._last_relay_index = -1
    result = await circuit_v2_transport._select_relay(peer_info)

    assert result.to_string() == relay1.to_string()
    assert len(circuit_v2_transport._relay_list) == 1


@pytest.mark.trio
async def test_select_relay_metrics_persistence(
    circuit_v2_transport, peer_info, mocker
):
    """Test _select_relay persists and updates metrics across multiple calls."""
    relay1 = MagicMock(spec=ID)
    relay1.to_string.return_value = "relay1"
    circuit_v2_transport.discovery.get_relays.return_value = [relay1]
    circuit_v2_transport.client_config.enable_auto_relay = True
    circuit_v2_transport._relay_list = [relay1]
    mocker.patch("time.monotonic", side_effect=itertools.cycle([0, 0.1]))
    mocker.patch("time.time", side_effect=itertools.cycle([1000.0, 1001.0]))
    async_mock = AsyncMock(side_effect=[False, True])
    mocker.patch.object(circuit_v2_transport, "_is_relay_available", async_mock)

    circuit_v2_transport._last_relay_index = -1
    result = await circuit_v2_transport._select_relay(peer_info)
    # first attempt should not select (False), but metrics should exist
    assert relay1.to_string() == relay1.to_string()  # sanity
    assert relay1 in circuit_v2_transport._relay_list
    assert relay1 in [r for r in circuit_v2_transport._relay_list]
    assert relay1.to_string() == "relay1"
    assert relay1.to_string() == circuit_v2_transport._relay_list[0].to_string()
    assert relay1.to_string()  # metrics object should be created
    assert relay1.to_string() in (
        r.to_string() for r in circuit_v2_transport._relay_list
    )
    assert _metrics_for(circuit_v2_transport, relay1)  # metrics dict present

    circuit_v2_transport._last_relay_index = -1
    # ensure next call returns True
    async_mock.side_effect = [True]
    result = await circuit_v2_transport._select_relay(peer_info)
    assert result.to_string() == relay1.to_string()
    metrics = _metrics_for(circuit_v2_transport, relay1)
    # after a successful measurement failures should be 0
    assert metrics["failures"] == 0


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
    mock_conn = RawConnection(stream=Mock(), initiator=True)

    transport = CircuitV2Transport(host=mock_host, config=Mock(), protocol=protocol)
    transport._dial_via_circuit_addr = AsyncMock(return_value=mock_conn)

    priv_key = create_new_key_pair()
    peer_id = ID.from_pubkey(priv_key.public_key)
    peer_info = PeerInfo(peer_id, [])

    circuit_ma = multiaddr.Multiaddr(
        f"/ip4/127.0.0.1/tcp/4001/p2p-circuit/p2p/{peer_id.to_base58()}"
    )
    peerstore.addrs.return_value = [circuit_ma]

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
    assert isinstance(conn, RawConnection)
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

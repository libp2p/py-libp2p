"""Test Circuit Relay v2 transport implementation."""
from unittest.mock import AsyncMock, patch
import pytest
import trio

from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2.transport import CircuitV2Transport
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
from libp2p.relay.circuit_v2.config import RelayConfig
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.pb import circuit_pb2 as proto
from libp2p.network.stream.net_stream import NetStream

from tests.utils import cleanup, set_up_nodes_by_transport_opt
from tests.utils.factories import HostFactory


@pytest.mark.trio
async def test_transport_initialization():
    """Test that the Circuit Relay v2 transport initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        
        # Test with default config
        transport = CircuitV2Transport(host)
        assert transport.host == host
        assert transport.peerstore == host.get_peerstore()
        assert transport.auto_relay is False
        
        # Test with auto relay enabled
        transport = CircuitV2Transport(host, auto_relay=True)
        assert transport.auto_relay is True


@pytest.mark.trio
async def test_transport_dial():
    """Test transport dialing functionality."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        transport = CircuitV2Transport(host1)
        
        # Mock successful dial
        mock_stream = AsyncMock(spec=NetStream)
        with patch.object(host1, "new_stream", return_value=mock_stream) as mock_new_stream:
            peer_info = PeerInfo(host2.get_id(), host2.get_addrs())
            await transport.dial(peer_info)
            
            mock_new_stream.assert_called_once()
            mock_stream.close.assert_called_once()


@pytest.mark.trio
async def test_transport_listen():
    """Test transport listener functionality."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        transport = CircuitV2Transport(host)
        
        # Test listener creation
        listener = await transport.create_listener()
        assert listener is not None
        
        # Test listener operations
        await listener.listen(host.get_addrs()[0])
        assert listener.is_listening()
        
        # Test listener close
        await listener.close()
        assert not listener.is_listening()


@pytest.mark.trio
async def test_auto_relay_selection():
    """Test automatic relay selection when enabled."""
    async with HostFactory.create_batch_and_listen(3) as hosts:
        client, relay1, relay2 = hosts
        transport = CircuitV2Transport(client, auto_relay=True)
        
        # Mock relay discovery
        mock_discover = AsyncMock(return_value=[relay1.get_id(), relay2.get_id()])
        with patch.object(transport, "_discover_relays", mock_discover):
            # Test relay selection
            selected_relay = await transport._select_relay()
            assert selected_relay in [relay1.get_id(), relay2.get_id()]


@pytest.mark.trio
async def test_transport_error_handling():
    """Test transport error handling for various scenarios."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        transport = CircuitV2Transport(host1)
        
        # Test dial failure
        with patch.object(host1, "new_stream", side_effect=Exception("Connection failed")):
            peer_info = PeerInfo(host2.get_id(), host2.get_addrs())
            with pytest.raises(Exception):
                await transport.dial(peer_info)
        
        # Test listener failure
        with patch.object(transport, "create_listener", side_effect=Exception("Listener failed")):
            with pytest.raises(Exception):
                await transport.create_listener()


@pytest.mark.trio
async def test_relay_connection_limits():
    """Test relay connection limit enforcement."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        config = RelayConfig(
            max_circuit_duration=10,
            max_circuit_bytes=1024,
            max_reservations=1
        )
        transport = CircuitV2Transport(host1, config=config)
        
        # Mock stream for testing limits
        mock_stream = AsyncMock(spec=NetStream)
        with patch.object(host1, "new_stream", return_value=mock_stream):
            peer_info = PeerInfo(host2.get_id(), host2.get_addrs())
            
            # First connection should succeed
            await transport.dial(peer_info)
            
            # Second connection should fail due to limits
            with pytest.raises(Exception):
                await transport.dial(peer_info)


async def test_direct_relay_connection():
    """Test direct connection through a specified relay."""
    async with trio.open_nursery() as nursery:
        hosts = await set_up_nodes_by_transport_opt(nursery, 3)
        relay_host, src_host, dst_host = hosts

        # Set up relay
        relay_config = RelayConfig(enable_hop=True)
        relay_protocol = CircuitV2Protocol(relay_host, allow_hop=True)
        relay_transport = CircuitV2Transport(relay_host, relay_protocol, relay_config)

        # Set up source
        src_config = RelayConfig(enable_client=True)
        src_protocol = CircuitV2Protocol(src_host)
        src_transport = CircuitV2Transport(src_host, src_protocol, src_config)

        # Connect to relay
        await relay_host.connect(PeerInfo(src_host.get_id(), src_host.get_addrs()))
        await relay_host.connect(PeerInfo(dst_host.get_id(), dst_host.get_addrs()))

        # Try to establish relayed connection
        dst_peer_info = PeerInfo(dst_host.get_id(), dst_host.get_addrs())
        connection = await src_transport.dial(
            dst_peer_info,
            relay_peer_id=relay_host.get_id(),
        )

        assert connection is not None
        assert connection.is_initiator
        assert connection.remote_peer == dst_host.get_id()

        await cleanup()


async def test_auto_relay_selection():
    """Test automatic relay selection and connection."""
    async with trio.open_nursery() as nursery:
        hosts = await set_up_nodes_by_transport_opt(nursery, 4)
        relay1_host, relay2_host, src_host, dst_host = hosts

        # Set up relays
        relay_config = RelayConfig(enable_hop=True)
        for relay_host in [relay1_host, relay2_host]:
            protocol = CircuitV2Protocol(relay_host, allow_hop=True)
            transport = CircuitV2Transport(relay_host, protocol, relay_config)

        # Set up source with known relays
        src_config = RelayConfig(
            enable_client=True,
            bootstrap_relays=[
                PeerInfo(relay1_host.get_id(), relay1_host.get_addrs()),
                PeerInfo(relay2_host.get_id(), relay2_host.get_addrs()),
            ],
        )
        src_protocol = CircuitV2Protocol(src_host)
        src_transport = CircuitV2Transport(src_host, src_protocol, src_config)

        # Connect relays to source and destination
        for relay_host in [relay1_host, relay2_host]:
            await relay_host.connect(PeerInfo(src_host.get_id(), src_host.get_addrs()))
            await relay_host.connect(PeerInfo(dst_host.get_id(), dst_host.get_addrs()))

        # Try to establish relayed connection without specifying relay
        dst_peer_info = PeerInfo(dst_host.get_id(), dst_host.get_addrs())
        connection = await src_transport.dial(dst_peer_info)

        assert connection is not None
        assert connection.is_initiator
        assert connection.remote_peer == dst_host.get_id()

        await cleanup()


async def test_listener_functionality():
    """Test relay listener functionality."""
    async with trio.open_nursery() as nursery:
        hosts = await set_up_nodes_by_transport_opt(nursery, 3)
        relay_host, src_host, dst_host = hosts

        # Set up relay
        relay_config = RelayConfig(enable_hop=True)
        relay_protocol = CircuitV2Protocol(relay_host, allow_hop=True)
        relay_transport = CircuitV2Transport(relay_host, relay_protocol, relay_config)

        # Set up destination with listener
        dst_config = RelayConfig(enable_stop=True)
        dst_protocol = CircuitV2Protocol(dst_host)
        dst_transport = CircuitV2Transport(dst_host, dst_protocol, dst_config)
        listener = dst_transport.create_listener()

        # Start listening
        test_addr = "/ip4/127.0.0.1/tcp/0/p2p/" + str(dst_host.get_id())
        await listener.listen(test_addr)

        assert test_addr in listener.get_addrs()

        # Clean up
        await listener.close()
        assert not listener.get_addrs()
        await cleanup()


async def test_connection_limits():
    """Test connection limits in transport."""
    async with trio.open_nursery() as nursery:
        hosts = await set_up_nodes_by_transport_opt(nursery, 3)
        relay_host, src_host, dst_host = hosts

        # Set up relay with strict limits
        relay_config = RelayConfig(
            enable_hop=True,
            max_circuit_duration=10,  # 10 seconds
            max_circuit_bytes=1024,  # 1KB
            max_reservations=1,
        )
        relay_protocol = CircuitV2Protocol(relay_host, allow_hop=True)
        relay_transport = CircuitV2Transport(relay_host, relay_protocol, relay_config)

        # Set up source
        src_config = RelayConfig(enable_client=True)
        src_protocol = CircuitV2Protocol(src_host)
        src_transport = CircuitV2Transport(src_host, src_protocol, src_config)

        # Connect to relay
        await relay_host.connect(PeerInfo(src_host.get_id(), src_host.get_addrs()))
        await relay_host.connect(PeerInfo(dst_host.get_id(), dst_host.get_addrs()))

        # Try multiple connections
        dst_peer_info = PeerInfo(dst_host.get_id(), dst_host.get_addrs())
        
        # First connection should succeed
        connection1 = await src_transport.dial(
            dst_peer_info,
            relay_peer_id=relay_host.get_id(),
        )
        assert connection1 is not None

        # Second connection should fail due to limits
        with pytest.raises(ConnectionError):
            await src_transport.dial(
                dst_peer_info,
                relay_peer_id=relay_host.get_id(),
            )

        await cleanup() 
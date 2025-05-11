"""Test Circuit Relay v2 discovery implementation."""
from unittest.mock import AsyncMock, patch
import pytest
import trio

from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.config import RelayConfig
from libp2p.relay.circuit_v2.pb import circuit_pb2 as proto
from libp2p.network.stream.net_stream import NetStream

from tests.utils.factories import HostFactory


@pytest.mark.trio
async def test_discovery_initialization():
    """Test that the Circuit Relay v2 discovery initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        
        # Test with default config
        discovery = RelayDiscovery(host)
        assert discovery.host == host
        assert discovery.peerstore == host.get_peerstore()
        assert discovery.max_relays == RelayDiscovery.DEFAULT_MAX_RELAYS
        
        # Test with custom config
        discovery = RelayDiscovery(host, max_relays=5)
        assert discovery.max_relays == 5


@pytest.mark.trio
async def test_relay_discovery():
    """Test relay discovery functionality."""
    async with HostFactory.create_batch_and_listen(3) as hosts:
        client, relay1, relay2 = hosts
        discovery = RelayDiscovery(client)
        
        # Mock peer discovery
        mock_peers = [relay1.get_id(), relay2.get_id()]
        with patch.object(discovery, "_find_relay_peers", return_value=mock_peers):
            # Test relay discovery
            discovered = await discovery.find_relays()
            assert len(discovered) <= discovery.max_relays
            assert all(peer in mock_peers for peer in discovered)


@pytest.mark.trio
async def test_relay_testing():
    """Test relay testing and validation."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        client, relay = hosts
        discovery = RelayDiscovery(client)
        
        # Mock successful relay test
        mock_stream = AsyncMock(spec=NetStream)
        with patch.object(client, "new_stream", return_value=mock_stream):
            is_valid = await discovery._test_relay(relay.get_id())
            assert is_valid
            mock_stream.close.assert_called_once()
        
        # Mock failed relay test
        with patch.object(client, "new_stream", side_effect=Exception("Connection failed")):
            is_valid = await discovery._test_relay(relay.get_id())
            assert not is_valid


@pytest.mark.trio
async def test_relay_selection():
    """Test relay selection process."""
    async with HostFactory.create_batch_and_listen(4) as hosts:
        client = hosts[0]
        relays = hosts[1:]
        discovery = RelayDiscovery(client)
        
        # Mock relay testing results
        async def mock_test_relay(peer_id):
            return peer_id == relays[0].get_id()  # Only first relay is valid
            
        with patch.object(discovery, "_test_relay", side_effect=mock_test_relay):
            relay_ids = [h.get_id() for h in relays]
            selected = await discovery._select_valid_relays(relay_ids)
            
            assert len(selected) == 1
            assert selected[0] == relays[0].get_id()


@pytest.mark.trio
async def test_discovery_limits():
    """Test discovery limit enforcement."""
    async with HostFactory.create_batch_and_listen(5) as hosts:
        client = hosts[0]
        relays = hosts[1:]
        max_relays = 2
        discovery = RelayDiscovery(client, max_relays=max_relays)
        
        # Mock all relays as valid
        with patch.object(discovery, "_test_relay", return_value=True):
            relay_ids = [h.get_id() for h in relays]
            selected = await discovery._select_valid_relays(relay_ids)
            
            assert len(selected) <= max_relays


@pytest.mark.trio
async def test_discovery_error_handling():
    """Test discovery error handling for various scenarios."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        client, relay = hosts
        discovery = RelayDiscovery(client)
        
        # Test peer discovery failure
        with patch.object(discovery, "_find_relay_peers", side_effect=Exception("Discovery failed")):
            discovered = await discovery.find_relays()
            assert len(discovered) == 0
        
        # Test relay testing failure
        with patch.object(client, "new_stream", side_effect=Exception("Stream failed")):
            is_valid = await discovery._test_relay(relay.get_id())
            assert not is_valid 
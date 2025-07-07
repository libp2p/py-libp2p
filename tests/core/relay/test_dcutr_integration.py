"""Integration tests for DCUtR with Circuit Relay v2."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import trio
from multiaddr import Multiaddr

from libp2p.peer.id import (
    ID,
)
from libp2p.relay.circuit_v2.dcutr import (
    DCUtRProtocol,
)
from libp2p.relay.circuit_v2.protocol import (
    CircuitV2Protocol,
)
from libp2p.relay.circuit_v2.resources import (
    RelayLimits,
)
from libp2p.tools.async_service import (
    background_trio_service,
)

logger = logging.getLogger(__name__)

# Test timeouts
SLEEP_TIME = 1.0  # seconds


@pytest.mark.trio
async def test_dcutr_with_relay_setup():
    """Test basic setup of DCUtR with Circuit Relay v2."""
    # Create mock hosts
    relay_host = MagicMock()
    relay_host._stream_handler = {}
    peer1_host = MagicMock()
    peer1_host._stream_handler = {}
    peer2_host = MagicMock()
    peer2_host._stream_handlers = {}
    
    # Mock IDs
    relay_id = ID("QmRelayPeerID")
    peer1_id = ID("QmPeer1ID")
    peer2_id = ID("QmPeer2ID")
    
    relay_host.get_id = MagicMock(return_value=relay_id)
    peer1_host.get_id = MagicMock(return_value=peer1_id)
    peer2_host.get_id = MagicMock(return_value=peer2_id)
    
    # Mock the set_stream_handler method
    relay_host.set_stream_handler = AsyncMock()
    peer1_host.set_stream_handler = AsyncMock()
    peer2_host.set_stream_handler = AsyncMock()
    
    # Mock connected peers
    peer1_host.get_connected_peers = MagicMock(return_value=[relay_id])
    peer2_host.get_connected_peers = MagicMock(return_value=[relay_id])
    
    # Set up the relay host with Circuit Relay v2 protocol
    relay_limits = RelayLimits(
        duration=60 * 60,  # 1 hour
        data=1024 * 1024,  # 1MB
        max_circuit_conns=8,
        max_reservations=4,
    )
    
    # Create and start the relay protocol
    relay_protocol = CircuitV2Protocol(
        relay_host,
        limits=relay_limits,
        allow_hop=True,
    )
    
    # Set up DCUtR on peer1 and peer2
    dcutr1 = DCUtRProtocol(peer1_host)
    dcutr2 = DCUtRProtocol(peer2_host)
    
    # Patch the run methods to avoid hanging
    with patch.object(relay_protocol, 'run') as mock_relay_run, \
         patch.object(dcutr1, 'run') as mock_dcutr1_run, \
         patch.object(dcutr2, 'run') as mock_dcutr2_run:
        
        # Make mock_run return a coroutine that completes quickly
        async def mock_run_impl(*, task_status=trio.TASK_STATUS_IGNORED):
            task_status.started()
            await trio.sleep(0.1)
        
        mock_relay_run.side_effect = mock_run_impl
        mock_dcutr1_run.side_effect = mock_run_impl
        mock_dcutr2_run.side_effect = mock_run_impl
        
        # Start all protocols with timeouts
        with trio.move_on_after(5):  # 5 second timeout
            async with background_trio_service(relay_protocol):
                async with background_trio_service(dcutr1):
                    async with background_trio_service(dcutr2):
                        # Wait for all protocols to start
                        await relay_protocol.event_started.wait()
                        await dcutr1.event_started.wait()
                        await dcutr2.event_started.wait()
                        
                        # Verify protocols are registered
                        assert relay_host.set_stream_handler.called
                        assert peer1_host.set_stream_handler.called
                        assert peer2_host.set_stream_handler.called
                        
                        # Wait a bit to ensure everything is set up
                        await trio.sleep(SLEEP_TIME)


@pytest.mark.trio
async def test_dcutr_direct_connection_detection():
    """Test DCUtR's ability to detect direct connections."""
    # Create mock hosts
    host1 = MagicMock()
    host2 = MagicMock()
    
    # Mock peer IDs
    peer1_id = ID("QmPeer1ID")
    peer2_id = ID("QmPeer2ID")
    
    host1.get_id = MagicMock(return_value=peer1_id)
    host2.get_id = MagicMock(return_value=peer2_id)
    
    # Mock network and connections
    mock_network = MagicMock()
    host1.get_network = MagicMock(return_value=mock_network)
    
    # Initially no connections
    mock_network.connections = {}
    
    # Create DCUtR protocol
    dcutr = DCUtRProtocol(host1)
    
    # Patch the run method
    with patch.object(dcutr, 'run') as mock_run:
        async def mock_run_impl(*, task_status=trio.TASK_STATUS_IGNORED):
            task_status.started()
            await trio.sleep(0.1)
        
        mock_run.side_effect = mock_run_impl
        
        # Start the protocol with timeout
        with trio.move_on_after(5):
            async with background_trio_service(dcutr):
                # Wait for the protocol to start
                await dcutr.event_started.wait()
                
                # Initially there should be no direct connection
                has_direct_connection = await dcutr._have_direct_connection(peer2_id)
                assert has_direct_connection is False
                
                # Mock a direct connection
                mock_conn = MagicMock()
                mock_conn.get_transport_addresses = MagicMock(
                    return_value=[
                        # Non-relay address indicates direct connection
                        "/ip4/192.168.1.1/tcp/1234"
                    ]
                )
                
                # Add the connection to the network
                mock_network.connections[peer2_id] = [mock_conn]
                
                # Now there should be a direct connection
                has_direct_connection = await dcutr._have_direct_connection(peer2_id)
                assert has_direct_connection is True
                
                # Verify the connection is cached
                assert peer2_id in dcutr._direct_connections


@pytest.mark.trio
async def test_dcutr_address_exchange():
    """Test DCUtR's ability to exchange and decode addresses."""
    # Create a mock host
    host = MagicMock()
    
    # Mock get_addrs method to return Multiaddr objects
    host.get_addrs = MagicMock(
        return_value=[
            Multiaddr("/ip4/127.0.0.1/tcp/1234"),
            Multiaddr("/ip4/192.168.1.1/tcp/5678"),
            Multiaddr("/ip4/8.8.8.8/tcp/9012"),
        ]
    )
    
    # Create DCUtR protocol with mocked host
    dcutr = DCUtRProtocol(host)
    
    # Patch the run method
    with patch.object(dcutr, 'run') as mock_run:
        async def mock_run_impl(*, task_status=trio.TASK_STATUS_IGNORED):
            task_status.started()
            await trio.sleep(0.1)
        
        mock_run.side_effect = mock_run_impl
        
        # Start the protocol with timeout
        with trio.move_on_after(5):
            async with background_trio_service(dcutr):
                # Wait for the protocol to start
                await dcutr.event_started.wait()
                
                # Test _get_observed_addrs method
                addr_bytes = await dcutr._get_observed_addrs()
                
                # Verify we got some addresses
                assert len(addr_bytes) > 0
                
                # Test _decode_observed_addrs method
                valid_addr_bytes = [
                    b"/ip4/127.0.0.1/tcp/1234",
                    b"/ip4/192.168.1.1/tcp/5678",
                ]
                invalid_addr_bytes = [
                    b"not-a-multiaddr",
                    b"also-invalid",
                ]
                
                # Test with valid addresses
                decoded_valid = dcutr._decode_observed_addrs(valid_addr_bytes)
                assert len(decoded_valid) == 2
                
                # Test with mixed addresses
                mixed_addrs = valid_addr_bytes + invalid_addr_bytes
                decoded_mixed = dcutr._decode_observed_addrs(mixed_addrs)
                
                # Should only have the valid addresses
                assert len(decoded_mixed) == 2 
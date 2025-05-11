"""Test Circuit Relay v2 protocol implementation."""
from unittest.mock import AsyncMock, patch
import pytest
import trio

from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol, PROTOCOL_ID
from libp2p.relay.circuit_v2.config import RelayConfig
from libp2p.relay.circuit_v2.pb import circuit_pb2 as proto
from libp2p.network.stream.net_stream import NetStream

from tests.utils import cleanup
from tests.utils.factories import HostFactory


@pytest.mark.trio
async def test_protocol_initialization():
    """Test that the Circuit Relay v2 protocol initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        
        # Test with default config
        protocol = CircuitV2Protocol(host)
        assert not protocol.allow_hop
        assert protocol.limits is not None
        assert protocol.host == host
        assert protocol.peerstore == host.get_peerstore()

        # Test with custom config
        custom_config = RelayConfig(
            enable_hop=True,
            max_circuit_duration=60,
            max_circuit_bytes=1024*1024,
            max_reservations=10
        )
        protocol = CircuitV2Protocol(host, allow_hop=True, limits=custom_config.limits)
        assert protocol.allow_hop
        assert protocol.limits.duration == 60
        assert protocol.limits.data == 1024*1024
        assert protocol.limits.max_reservations == 10


@pytest.mark.trio
async def test_handle_reservation_request():
    """Test handling of relay reservation requests."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        protocol = CircuitV2Protocol(host, allow_hop=True)
        
        # Create mock stream and client
        mock_stream = AsyncMock(spec=NetStream)
        client_id = ID("client_peer")
        
        # Test successful reservation
        reserve_msg = proto.HopMessage(
            type=proto.HopMessage.RESERVE,
            peer=client_id.to_bytes()
        )
        mock_stream.read.return_value = reserve_msg.SerializeToString()
        
        await protocol.handle_reservation(mock_stream)
        
        # Verify response was written
        mock_stream.write.assert_called_once()
        response = proto.HopMessage()
        response.ParseFromString(mock_stream.write.call_args[0][0])
        assert response.type == proto.HopMessage.STATUS
        assert response.status.code == proto.Status.OK
        assert response.HasField("reservation")


@pytest.mark.trio
async def test_handle_connect_request():
    """Test handling of relay connection requests."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        protocol = CircuitV2Protocol(host, allow_hop=True)
        
        # Create mock stream and peers
        mock_stream = AsyncMock(spec=NetStream)
        src_id = ID("source_peer")
        dst_id = ID("dest_peer")
        
        # Test connection request
        connect_msg = proto.HopMessage(
            type=proto.HopMessage.CONNECT,
            peer=dst_id.to_bytes()
        )
        mock_stream.read.return_value = connect_msg.SerializeToString()
        
        with patch.object(protocol, "_handle_connect") as mock_handle_connect:
            mock_handle_connect.return_value = True
            await protocol.handle_stream(mock_stream)
            
            mock_handle_connect.assert_called_once()
            mock_stream.close.assert_called_once()


@pytest.mark.trio
async def test_resource_limit_enforcement():
    """Test that resource limits are properly enforced."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        strict_limits = RelayConfig(
            enable_hop=True,
            max_circuit_duration=10,
            max_circuit_bytes=1024,
            max_reservations=1
        )
        protocol = CircuitV2Protocol(host, allow_hop=True, limits=strict_limits.limits)
        
        # Test reservation limit
        mock_stream = AsyncMock(spec=NetStream)
        client_id = ID("client_peer")
        
        # First reservation should succeed
        reserve_msg = proto.HopMessage(
            type=proto.HopMessage.RESERVE,
            peer=client_id.to_bytes()
        )
        mock_stream.read.return_value = reserve_msg.SerializeToString()
        
        await protocol.handle_reservation(mock_stream)
        
        response1 = proto.HopMessage()
        response1.ParseFromString(mock_stream.write.call_args[0][0])
        assert response1.status.code == proto.Status.OK
        
        # Second reservation should fail
        mock_stream.reset_mock()
        await protocol.handle_reservation(mock_stream)
        
        response2 = proto.HopMessage()
        response2.ParseFromString(mock_stream.write.call_args[0][0])
        assert response2.status.code == proto.Status.RESOURCE_LIMIT_EXCEEDED


@pytest.mark.trio
async def test_error_handling():
    """Test protocol error handling for various scenarios."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        protocol = CircuitV2Protocol(host, allow_hop=True)
        
        # Test invalid message type
        mock_stream = AsyncMock(spec=NetStream)
        invalid_msg = proto.HopMessage(
            type=999,
            peer=ID("peer").to_bytes()
        )
        mock_stream.read.return_value = invalid_msg.SerializeToString()
        
        await protocol.handle_stream(mock_stream)
        
        response = proto.HopMessage()
        response.ParseFromString(mock_stream.write.call_args[0][0])
        assert response.status.code == proto.Status.MALFORMED_MESSAGE
        
        # Test malformed message
        mock_stream.reset_mock()
        mock_stream.read.return_value = b"invalid data"
        
        await protocol.handle_stream(mock_stream)
        
        response = proto.HopMessage()
        response.ParseFromString(mock_stream.write.call_args[0][0])
        assert response.status.code == proto.Status.MALFORMED_MESSAGE 
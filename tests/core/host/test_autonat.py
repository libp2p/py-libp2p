from unittest.mock import (
    AsyncMock,
    patch,
)

import pytest

from libp2p.host.autonat.autonat import (
    AUTONAT_PROTOCOL_ID,
    AutoNATService,
    AutoNATStatus,
)
from libp2p.host.autonat.pb.autonat_pb2 import (
    DialRequest,
    DialResponse,
    Message,
    PeerInfo,
    Status,
    Type,
)
from libp2p.network.stream.exceptions import (
    StreamError,
)
from libp2p.network.stream.net_stream import (
    NetStream,
)
from libp2p.peer.id import (
    ID,
)
from tests.utils.factories import (
    HostFactory,
)


@pytest.mark.trio
async def test_autonat_service_initialization():
    """Test that the AutoNAT service initializes correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        assert service.status == AutoNATStatus.UNKNOWN
        assert service.dial_results == {}
        assert service.host == host
        assert service.peerstore == host.get_peerstore()


@pytest.mark.trio
async def test_autonat_status_getter():
    """Test that the AutoNAT status getter works correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        # Testing the initial status
        assert service.get_status() == AutoNATStatus.UNKNOWN

        # Testing the status changes
        service.status = AutoNATStatus.PUBLIC
        assert service.get_status() == AutoNATStatus.PUBLIC

        service.status = AutoNATStatus.PRIVATE
        assert service.get_status() == AutoNATStatus.PRIVATE


@pytest.mark.trio
async def test_update_status():
    """Test that the AutoNAT status updates correctly based on dial results."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        # No dial results should result in UNKNOWN status
        service.update_status()
        assert service.status == AutoNATStatus.UNKNOWN

        # Less than 2 successful dials should result in PRIVATE status
        service.dial_results = {
            ID(b"peer1"): True,
            ID(b"peer2"): False,
            ID(b"peer3"): False,
        }
        service.update_status()
        assert service.status == AutoNATStatus.PRIVATE

        # 2 or more successful dials should result in PUBLIC status
        service.dial_results = {
            ID(b"peer1"): True,
            ID(b"peer2"): True,
            ID(b"peer3"): False,
        }
        service.update_status()
        assert service.status == AutoNATStatus.PUBLIC


@pytest.mark.trio
async def test_try_dial():
    """Test that the try_dial method works correctly."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        peer_id = host2.get_id()

        # Test successful dial
        with patch.object(
            host1, "new_stream", new_callable=AsyncMock
        ) as mock_new_stream:
            mock_stream = AsyncMock(spec=NetStream)
            mock_new_stream.return_value = mock_stream

            result = await service._try_dial(peer_id)

            assert result is True
            mock_new_stream.assert_called_once_with(peer_id, [AUTONAT_PROTOCOL_ID])
            mock_stream.close.assert_called_once()

        # Test failed dial
        with patch.object(
            host1, "new_stream", new_callable=AsyncMock
        ) as mock_new_stream:
            mock_new_stream.side_effect = Exception("Connection failed")

            result = await service._try_dial(peer_id)

            assert result is False
            mock_new_stream.assert_called_once_with(peer_id, [AUTONAT_PROTOCOL_ID])


@pytest.mark.trio
async def test_handle_dial():
    """Test that the handle_dial method works correctly."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        peer_id = host2.get_id()

        # Create a mock message with a peer to dial
        message = Message()
        message.type = Type.Value("DIAL")
        peer_info = PeerInfo()
        peer_info.id = peer_id.to_bytes()
        peer_info.addrs.extend([b"/ip4/127.0.0.1/tcp/4001"])
        message.dial.peers.append(peer_info)

        # Mock the _try_dial method
        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = True

            response = await service._handle_dial(message)

            assert response.type == Type.Value("DIAL_RESPONSE")
            assert response.dial_response.status == Status.OK
            assert len(response.dial_response.peers) == 1
            assert response.dial_response.peers[0].id == peer_id.to_bytes()
            assert response.dial_response.peers[0].success is True
            mock_try_dial.assert_called_once_with(peer_id)


@pytest.mark.trio
async def test_handle_request():
    """Test that the handle_request method works correctly."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        service = AutoNATService(host)

        # Test handling a DIAL request
        message = Message()
        message.type = Type.DIAL
        dial_request = DialRequest()
        peer_info = PeerInfo()
        dial_request.peers.append(peer_info)
        message.dial.CopyFrom(dial_request)

        with patch.object(
            service, "_handle_dial", new_callable=AsyncMock
        ) as mock_handle_dial:
            mock_handle_dial.return_value = Message()

            response = await service._handle_request(message.SerializeToString())

            mock_handle_dial.assert_called_once()
            assert isinstance(response, Message)

        # Test handling an unknown request type
        message = Message()
        message.type = Type.UNKNOWN

        response = await service._handle_request(message.SerializeToString())

        assert isinstance(response, Message)
        assert response.type == Type.DIAL_RESPONSE
        assert response.dial_response.status == Status.E_INTERNAL_ERROR


@pytest.mark.trio
async def test_handle_stream():
    """Test that handle_stream correctly processes stream data."""
    async with HostFactory.create_batch_and_listen(1) as hosts:
        host = hosts[0]
        autonat_service = AutoNATService(host)

        # Create a mock stream
        mock_stream = AsyncMock(spec=NetStream)

        # Create a properly initialized request Message
        request = Message()
        request.type = Type.DIAL
        dial_request = DialRequest()
        peer_info = PeerInfo()
        peer_info.id = b"peer_id"
        peer_info.addrs.append(b"addr1")
        dial_request.peers.append(peer_info)
        request.dial.CopyFrom(dial_request)

        # Create a properly initialized response Message
        response = Message()
        response.type = Type.DIAL_RESPONSE
        dial_response = DialResponse()
        dial_response.status = Status.OK
        dial_response.peers.append(peer_info)
        response.dial_response.CopyFrom(dial_response)

        # Mock stream read/write and _handle_request
        mock_stream.read.return_value = request.SerializeToString()
        mock_stream.write.return_value = None
        autonat_service._handle_request = AsyncMock(return_value=response)

        # Test successful stream handling
        await autonat_service.handle_stream(mock_stream)
        mock_stream.read.assert_called_once()
        mock_stream.write.assert_called_once_with(response.SerializeToString())
        mock_stream.close.assert_called_once()

        # Test stream error handling
        mock_stream.reset_mock()
        mock_stream.read.side_effect = StreamError("Stream error")
        await autonat_service.handle_stream(mock_stream)
        mock_stream.close.assert_called_once()

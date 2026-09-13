from unittest.mock import (
    AsyncMock,
    patch,
)

import pytest

from libp2p.host.autonat.autonat import (
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
from libp2p.io.abc import Reader
from libp2p.network.stream.exceptions import (
    StreamError,
)
from libp2p.network.stream.net_stream import (
    NetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.utils.varint import (
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
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
    """Test that the try_dial method dials each address and reports back."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        peer_id = host2.get_id()
        addr = b"/ip4/127.0.0.1/tcp/4001"

        # Test successful dial returns the dialed address
        with patch.object(host1, "connect", new_callable=AsyncMock) as mock_connect:
            result = await service._try_dial(peer_id, [addr])

            assert result == addr
            mock_connect.assert_called_once()
            assert service.dial_results == {}

        # Test failed dial returns None
        with patch.object(host1, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            result = await service._try_dial(peer_id, [addr])

            assert result is None


@pytest.mark.trio
async def test_handle_dial():
    """Test that the handle_dial method works correctly."""
    async with HostFactory.create_batch_and_listen(2) as hosts:
        host1, host2 = hosts
        service = AutoNATService(host1)
        peer_id = host2.get_id()

        # Create a request asking for a dial-back
        message = Message()
        message.type = Type.DIAL
        message.dial.peer.id = peer_id.to_bytes()
        message.dial.peer.addrs.append(b"/ip4/127.0.0.1/tcp/4001")

        # Mock the _try_dial method
        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = b"/ip4/127.0.0.1/tcp/4001"

            response = await service._handle_dial(message)

            assert response.type == Type.DIAL_RESPONSE
            assert response.dial_response.status == Status.OK
            assert response.dial_response.addr == b"/ip4/127.0.0.1/tcp/4001"
            assert service.dial_results[peer_id] is True
            mock_try_dial.assert_called_once_with(peer_id, [b"/ip4/127.0.0.1/tcp/4001"])

        # Failed dial-back yields E_DIAL_ERROR
        with patch.object(
            service, "_try_dial", new_callable=AsyncMock
        ) as mock_try_dial:
            mock_try_dial.return_value = None

            response = await service._handle_dial(message)

            assert response.type == Type.DIAL_RESPONSE
            assert response.dial_response.status == Status.E_DIAL_ERROR
            assert service.dial_results[peer_id] is False


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
        message.type = Type.DIAL_RESPONSE

        response = await service._handle_request(message.SerializeToString())

        assert isinstance(response, Message)
        assert response.type == Type.DIAL_RESPONSE
        assert response.dial_response.status == Status.E_INTERNAL_ERROR


@pytest.mark.trio
async def test_handle_stream():
    """Test that handle_stream speaks length-delimited framing."""
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
        dial_request.peer.CopyFrom(peer_info)
        request.dial.CopyFrom(dial_request)

        # Create a properly initialized response Message
        response = Message()
        response.type = Type.DIAL_RESPONSE
        dial_response = DialResponse()
        dial_response.status = Status.OK
        dial_response.addr = b"addr1"
        response.dial_response.CopyFrom(dial_response)

        # Mock stream read/write and _handle_request: the request arrives
        # length-prefixed, and the response must leave length-prefixed.
        framed = encode_varint_prefixed(request.SerializeToString())
        mock_stream.read = AsyncMock(
            side_effect=[framed[i : i + 1] for i in range(len(framed))]
        )
        mock_stream.write.return_value = None
        autonat_service._handle_request = AsyncMock(return_value=response)

        # Test successful stream handling
        await autonat_service.handle_stream(mock_stream)
        written = mock_stream.write.await_args.args[0]
        assert await read_varint_prefixed_bytes(_BytesReader(written)) == (
            response.SerializeToString()
        )
        mock_stream.close.assert_called_once()

        # Test stream error handling
        mock_stream.reset_mock()
        mock_stream.read.side_effect = StreamError("Stream error")
        await autonat_service.handle_stream(mock_stream)
        mock_stream.close.assert_called_once()


class _BytesReader(Reader):
    """Minimal async reader over bytes for delimited framing helpers."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def read(self, n: int | None = None) -> bytes:
        if n is None or n < 0:
            n = len(self._data) - self._pos
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

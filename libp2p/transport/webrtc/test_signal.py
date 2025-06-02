from unittest.mock import Mock
import json
import trio
from wsgiref.types import InputStream
import pytest
from libp2p.abc import (
    IHost,
    INetStream,
    INotifee,
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)
from .signal_service import (
    SignalService
)

SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")


class TestSignalService:

    # Registering a handler for a specific message type and receiving that message type
    @pytest.mark.trio
    async def test_register_handler_and_receive_message(self):
        mock_host = Mock(spec=IHost)
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_peer_id = ID(b"test_peer_id")

        mock_muxed_conn.peer_id = mock_peer_id
        mock_stream.muxed_conn = mock_muxed_conn

        message = {"type": "test_type", "data": "test_data"}
        encoded_message = json.dumps(message).encode()

        # Configure read to return the message once, then empty data
        mock_stream.read.side_effect = [encoded_message, b""]
        signal_service = SignalService(mock_host)

        received_message = None
        received_peer_id = None
        handler_called_event = trio.Event()

        async def test_handler(msg, peer_id):
            nonlocal received_message, received_peer_id
            received_message = msg
            received_peer_id = peer_id
            handler_called_event.set()

        signal_service.set_handler("test_type", test_handler)
        await signal_service.listen()

        mock_host.set_stream_handler.assert_called_once_with(
            SIGNAL_PROTOCOL, signal_service.handle_signal
        )

        async with trio.open_nursery() as nursery:
            nursery.start_soon(signal_service.handle_signal, mock_stream)
            await handler_called_event.wait()

        assert received_message == message
        assert received_peer_id == str(mock_peer_id)
        assert mock_stream.read.call_count == 2


    # Handling empty data received from a stream
    @pytest.mark.trio
    async def test_handle_empty_data(self):
        mock_host = Mock(spec=IHost)
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_peer_id = ID(b"test_peer_id")
    
        mock_muxed_conn.peer_id = mock_peer_id
        mock_stream.muxed_conn = mock_muxed_conn
    
        # Configure read to return empty data immediately
        mock_stream.read.return_value = b""

        signal_service = SignalService(mock_host)
    
        handler_called = False
    
        async def test_handler(msg, peer_id):
            nonlocal handler_called
            handler_called = True
    
        signal_service.set_handler("test_type", test_handler)
    
        await signal_service.handle_signal(mock_stream)

        assert not handler_called
        mock_stream.read.assert_called_once_with(4096)
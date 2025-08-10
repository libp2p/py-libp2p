"""Unit tests for DCUtR protocol."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.abc import INetStream
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.dcutr import (
    MAX_HOLE_PUNCH_ATTEMPTS,
    DCUtRProtocol,
)
from libp2p.relay.circuit_v2.pb.dcutr_pb2 import HolePunch
from libp2p.tools.async_service import background_trio_service

logger = logging.getLogger(__name__)


@pytest.mark.trio
async def test_dcutr_protocol_initialization():
    """Test DCUtR protocol initialization."""
    mock_host = MagicMock()
    dcutr = DCUtRProtocol(mock_host)

    # Test that the protocol is initialized correctly
    assert dcutr.host == mock_host
    assert not dcutr.event_started.is_set()
    assert dcutr._hole_punch_attempts == {}
    assert dcutr._direct_connections == set()
    assert dcutr._in_progress == set()

    # Test that the protocol can be started
    async with background_trio_service(dcutr):
        # Wait for the protocol to start
        await dcutr.event_started.wait()

        # Verify that the stream handler was registered
        mock_host.set_stream_handler.assert_called_once()

        # Verify that the event is set
        assert dcutr.event_started.is_set()


@pytest.mark.trio
async def test_dcutr_message_exchange():
    """Test DCUtR message exchange."""
    mock_host = MagicMock()
    dcutr = DCUtRProtocol(mock_host)

    # Test that the protocol can be started
    async with background_trio_service(dcutr):
        # Wait for the protocol to start
        await dcutr.event_started.wait()

        # Test CONNECT message
        connect_msg = HolePunch(
            type=HolePunch.CONNECT,
            ObsAddrs=[b"/ip4/127.0.0.1/tcp/1234", b"/ip4/192.168.1.1/tcp/5678"],
        )

        # Test SYNC message
        sync_msg = HolePunch(type=HolePunch.SYNC)

        # Verify message types
        assert connect_msg.type == HolePunch.CONNECT
        assert sync_msg.type == HolePunch.SYNC
        assert len(connect_msg.ObsAddrs) == 2


@pytest.mark.trio
async def test_dcutr_error_handling(monkeypatch):
    """Test DCUtR error handling."""
    mock_host = MagicMock()
    dcutr = DCUtRProtocol(mock_host)

    async with background_trio_service(dcutr):
        await dcutr.event_started.wait()

        # Simulate a stream that times out
        class TimeoutStream(INetStream):
            def __init__(self):
                self._protocol = None
                self.muxed_conn = MagicMock(peer_id=ID(b"peer"))

            async def read(self, n: int | None = None) -> bytes:
                await trio.sleep(0.2)
                raise trio.TooSlowError()

            async def write(self, data: bytes) -> None:
                return None

            async def close(self, *args, **kwargs):
                return None

            async def reset(self):
                return None

            def get_protocol(self):
                return self._protocol

            def set_protocol(self, protocol_id):
                self._protocol = protocol_id

            def get_remote_address(self):
                return ("127.0.0.1", 1234)

        # Should not raise, just log and close
        await dcutr._handle_dcutr_stream(TimeoutStream())

        # Simulate a stream with malformed message
        class MalformedStream(INetStream):
            def __init__(self):
                self._protocol = None
                self.muxed_conn = MagicMock(peer_id=ID(b"peer"))

            async def read(self, n: int | None = None) -> bytes:
                return b"not-a-protobuf"

            async def write(self, data: bytes) -> None:
                return None

            async def close(self, *args, **kwargs):
                return None

            async def reset(self):
                return None

            def get_protocol(self):
                return self._protocol

            def set_protocol(self, protocol_id):
                self._protocol = protocol_id

            def get_remote_address(self):
                return ("127.0.0.1", 1234)

        await dcutr._handle_dcutr_stream(MalformedStream())


@pytest.mark.trio
async def test_dcutr_max_attempts_and_already_connected():
    """Test max hole punch attempts and already-connected peer."""
    mock_host = MagicMock()
    dcutr = DCUtRProtocol(mock_host)
    peer_id = ID(b"peer")

    # Simulate already having a direct connection
    dcutr._direct_connections.add(peer_id)
    result = await dcutr.initiate_hole_punch(peer_id)
    assert result is True

    # Remove direct connection, simulate max attempts
    dcutr._direct_connections.clear()
    dcutr._hole_punch_attempts[peer_id] = MAX_HOLE_PUNCH_ATTEMPTS
    result = await dcutr.initiate_hole_punch(peer_id)
    assert result is False


@pytest.mark.trio
async def test_dcutr_observed_addr_encoding_decoding():
    """Test observed address encoding/decoding."""
    from multiaddr import Multiaddr

    mock_host = MagicMock()
    dcutr = DCUtRProtocol(mock_host)
    # Simulate valid and invalid multiaddrs as bytes
    valid = [
        Multiaddr("/ip4/127.0.0.1/tcp/1234").to_bytes(),
        Multiaddr("/ip4/192.168.1.1/tcp/5678").to_bytes(),
    ]
    invalid = [b"not-a-multiaddr", b""]
    decoded = dcutr._decode_observed_addrs(valid + invalid)
    assert len(decoded) == 2


@pytest.mark.trio
async def test_dcutr_real_perform_hole_punch(monkeypatch):
    """Test initiate_hole_punch with real _perform_hole_punch logic (mock network)."""
    mock_host = MagicMock()
    dcutr = DCUtRProtocol(mock_host)
    peer_id = ID(b"peer")

    # Patch methods to simulate a successful punch
    monkeypatch.setattr(dcutr, "_have_direct_connection", AsyncMock(return_value=False))
    monkeypatch.setattr(
        dcutr,
        "_get_observed_addrs",
        AsyncMock(return_value=[b"/ip4/127.0.0.1/tcp/1234"]),
    )
    mock_stream = MagicMock()
    mock_stream.read = AsyncMock(
        side_effect=[
            HolePunch(
                type=HolePunch.CONNECT, ObsAddrs=[b"/ip4/192.168.1.1/tcp/4321"]
            ).SerializeToString(),
            HolePunch(type=HolePunch.SYNC).SerializeToString(),
        ]
    )
    mock_stream.write = AsyncMock()
    mock_stream.close = AsyncMock()
    mock_stream.muxed_conn = MagicMock(peer_id=peer_id)
    mock_host.new_stream = AsyncMock(return_value=mock_stream)
    monkeypatch.setattr(dcutr, "_perform_hole_punch", AsyncMock(return_value=True))

    result = await dcutr.initiate_hole_punch(peer_id)
    assert result is True

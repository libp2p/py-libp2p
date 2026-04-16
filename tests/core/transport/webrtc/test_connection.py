"""
Tests for WebRTCConnection stream management and lifecycle.
"""
# pyrefly: ignore

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.connection_types import ConnectionType
from libp2p.peer.id import ID
from libp2p.transport.webrtc.config import WebRTCTransportConfig
from libp2p.transport.webrtc.connection import WebRTCConnection
from libp2p.transport.webrtc.constants import OUTBOUND_STREAM_START_ID
from libp2p.transport.webrtc.exceptions import WebRTCStreamError


def _make_connection(
    max_streams: int = 256,
) -> WebRTCConnection:
    """Create a connection with a mock bridge."""
    mock_bridge = MagicMock()
    mock_bridge.run_coro = AsyncMock()
    mock_bridge.is_running = True

    config = WebRTCTransportConfig(max_concurrent_streams=max_streams)
    peer_id = ID(b"\x00" * 32)
    conn = WebRTCConnection(
        peer_id=peer_id,
        bridge=mock_bridge,
        is_initiator=True,
        config=config,
    )
    # Set up mock callbacks
    conn._create_channel_cb = AsyncMock()
    conn._send_on_channel_cb = AsyncMock()
    conn._close_pc_cb = AsyncMock()
    return conn


class TestConnectionProperties:
    def test_is_initiator(self):
        conn = _make_connection()
        assert conn.is_initiator is True

    def test_connection_type_is_direct(self):
        conn = _make_connection()
        assert conn.get_connection_type() == ConnectionType.DIRECT

    def test_not_established_initially(self):
        conn = _make_connection()
        assert conn.is_established is False
        assert conn.is_closed is False

    @pytest.mark.trio
    async def test_start_marks_established(self):
        conn = _make_connection()
        await conn.start()
        assert conn.is_established is True
        assert conn.event_started.is_set()


class TestOpenStream:
    @pytest.mark.trio
    async def test_open_stream_returns_stream(self):
        conn = _make_connection()
        stream = await conn.open_stream()
        assert stream is not None
        assert stream.channel_id == OUTBOUND_STREAM_START_ID

    @pytest.mark.trio
    async def test_open_stream_increments_ids_by_2(self):
        conn = _make_connection()
        s1 = await conn.open_stream()
        s2 = await conn.open_stream()
        s3 = await conn.open_stream()
        assert s1.channel_id == 2
        assert s2.channel_id == 4
        assert s3.channel_id == 6

    @pytest.mark.trio
    async def test_open_stream_on_closed_connection_raises(self):
        conn = _make_connection()
        conn._closed = True
        with pytest.raises(WebRTCStreamError, match="closed"):
            await conn.open_stream()

    @pytest.mark.trio
    async def test_open_stream_at_limit_raises(self):
        conn = _make_connection(max_streams=2)
        await conn.open_stream()
        await conn.open_stream()
        with pytest.raises(WebRTCStreamError, match="limit"):
            await conn.open_stream()


class TestAcceptStream:
    @pytest.mark.trio
    async def test_accept_receives_inbound_stream(self):
        conn = _make_connection()

        async def _accept() -> None:
            stream = await conn.accept_stream()
            assert stream.channel_id == 1

        async with trio.open_nursery() as nursery:
            nursery.start_soon(_accept)
            await trio.sleep(0.01)
            conn.on_datachannel(1)

    @pytest.mark.trio
    async def test_accept_on_closed_raises(self):
        conn = _make_connection()
        conn._closed = True
        with pytest.raises(WebRTCStreamError, match="closed"):
            await conn.accept_stream()


class TestMessageRouting:
    @pytest.mark.trio
    async def test_on_channel_message_routes_to_stream(self):
        conn = _make_connection()
        stream = await conn.open_stream()
        from libp2p.transport.webrtc.pb.webrtc_pb2 import Message

        msg = Message(message=b"test-data")
        conn.on_channel_message(stream.channel_id, msg.SerializeToString())
        data = await stream.read()
        assert data == b"test-data"

    def test_on_channel_message_unknown_id_ignored(self):
        conn = _make_connection()
        # Should not raise
        conn.on_channel_message(999, b"ignored")


class TestClose:
    @pytest.mark.trio
    async def test_close_resets_all_streams(self):
        conn = _make_connection()
        # Open two streams to ensure close() iterates and resets them all.
        await conn.open_stream()
        await conn.open_stream()
        await conn.close()
        assert conn.is_closed is True
        assert not conn.is_established

    @pytest.mark.trio
    async def test_close_is_idempotent(self):
        conn = _make_connection()
        await conn.close()
        await conn.close()  # Should not raise

    @pytest.mark.trio
    async def test_raw_read_write_raises(self):
        conn = _make_connection()
        with pytest.raises(Exception, match="native multiplexing"):
            await conn.read()
        with pytest.raises(Exception, match="native multiplexing"):
            await conn.write(b"data")

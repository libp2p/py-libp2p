"""
Tests for WebRTCStream protobuf framing and lifecycle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.transport.webrtc.pb.webrtc_pb2 import Message
from libp2p.transport.webrtc.stream import StreamState, WebRTCStream


def _make_stream(channel_id: int = 2) -> WebRTCStream:
    """Create a stream with a mock connection and send callback."""
    mock_conn = MagicMock()
    mock_conn.peer_id = MagicMock()
    stream = WebRTCStream(
        connection=mock_conn,
        channel_id=channel_id,
        is_initiator=True,
    )
    stream._send_callback = AsyncMock()
    return stream


class TestWrite:
    @pytest.mark.trio
    async def test_write_sends_protobuf_framed_data(self):
        stream = _make_stream()
        await stream.write(b"hello")
        stream._send_callback.assert_called_once()
        raw = stream._send_callback.call_args[0][0]
        msg = Message()
        msg.ParseFromString(raw)
        assert msg.message == b"hello"
        assert not msg.HasField("flag")

    @pytest.mark.trio
    async def test_write_chunks_large_data(self):
        stream = _make_stream()
        big = b"x" * 32768  # 2x max message size
        await stream.write(big)
        assert stream._send_callback.call_count == 2
        # First chunk is MAX_MESSAGE_SIZE
        raw1 = stream._send_callback.call_args_list[0][0][0]
        msg1 = Message()
        msg1.ParseFromString(raw1)
        assert len(msg1.message) == 16384

    @pytest.mark.trio
    async def test_write_after_close_raises(self):
        stream = _make_stream()
        stream._write_closed = True
        with pytest.raises(Exception, match="closed"):
            await stream.write(b"data")

    @pytest.mark.trio
    async def test_write_after_reset_raises(self):
        stream = _make_stream()
        stream._state = StreamState.RESET
        with pytest.raises(Exception, match="reset"):
            await stream.write(b"data")


class TestRead:
    @pytest.mark.trio
    async def test_read_returns_data_from_on_data(self):
        stream = _make_stream()
        # Simulate incoming data
        msg = Message(message=b"world")
        stream.on_data(msg.SerializeToString())
        data = await stream.read()
        assert data == b"world"

    @pytest.mark.trio
    async def test_read_after_reset_raises(self):
        stream = _make_stream()
        stream._state = StreamState.RESET
        with pytest.raises(Exception, match="reset"):
            await stream.read()

    @pytest.mark.trio
    async def test_read_buffers_partial(self):
        stream = _make_stream()
        msg = Message(message=b"abcdefgh")
        stream.on_data(msg.SerializeToString())
        # Read 3 bytes
        data = await stream.read(3)
        assert data == b"abc"
        # Read remaining
        data = await stream.read()
        assert data == b"defgh"


class TestFlags:
    @pytest.mark.trio
    async def test_on_data_fin_closes_read_and_sends_fin_ack(self):
        stream = _make_stream()
        fin_msg = Message(flag=Message.FIN)
        stream.on_data(fin_msg.SerializeToString())
        assert stream._read_closed is True

    @pytest.mark.trio
    async def test_on_data_fin_ack_sets_event(self):
        stream = _make_stream()
        ack_msg = Message(flag=Message.FIN_ACK)
        stream.on_data(ack_msg.SerializeToString())
        assert stream._fin_ack_received.is_set()

    @pytest.mark.trio
    async def test_on_data_stop_sending_closes_write(self):
        stream = _make_stream()
        stop_msg = Message(flag=Message.STOP_SENDING)
        stream.on_data(stop_msg.SerializeToString())
        assert stream._write_closed is True

    @pytest.mark.trio
    async def test_on_data_reset_sets_state(self):
        stream = _make_stream()
        reset_msg = Message(flag=Message.RESET)
        stream.on_data(reset_msg.SerializeToString())
        assert stream._state == StreamState.RESET

    @pytest.mark.trio
    async def test_on_data_with_flag_and_payload(self):
        stream = _make_stream()
        msg = Message(flag=Message.FIN, message=b"last-chunk")
        stream.on_data(msg.SerializeToString())
        # FIN should close reads but payload should be delivered
        data = await stream.read()
        assert data == b"last-chunk"


class TestClose:
    @pytest.mark.trio
    async def test_close_sends_fin(self):
        stream = _make_stream()
        # Pre-set FIN_ACK so close doesn't block
        stream._fin_ack_received.set()
        await stream.close()
        assert stream._state == StreamState.CLOSED
        # Should have sent FIN
        calls = stream._send_callback.call_args_list
        assert len(calls) >= 1
        msg = Message()
        msg.ParseFromString(calls[0][0][0])
        assert msg.flag == Message.FIN

    @pytest.mark.trio
    async def test_close_is_idempotent(self):
        stream = _make_stream()
        stream._fin_ack_received.set()
        await stream.close()
        await stream.close()  # Should not raise
        assert stream._state == StreamState.CLOSED

    @pytest.mark.trio
    async def test_reset_sends_reset_flag(self):
        stream = _make_stream()
        await stream.reset()
        assert stream._state == StreamState.RESET
        calls = stream._send_callback.call_args_list
        msg = Message()
        msg.ParseFromString(calls[0][0][0])
        assert msg.flag == Message.RESET


class TestDeadline:
    @pytest.mark.trio
    async def test_set_deadline(self):
        stream = _make_stream()
        stream.set_deadline(10)
        assert stream._deadline > 0

    @pytest.mark.trio
    async def test_clear_deadline(self):
        stream = _make_stream()
        stream.set_deadline(10)
        stream.set_deadline(0)
        assert stream._deadline == 0.0


class TestChannelClose:
    @pytest.mark.trio
    async def test_on_channel_close(self):
        stream = _make_stream()
        stream.on_channel_close()
        assert stream._read_closed is True
        assert stream._write_closed is True

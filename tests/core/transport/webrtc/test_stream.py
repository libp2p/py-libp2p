"""
Tests for WebRTCStream protobuf framing and lifecycle.
"""
# pyrefly: ignore

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from libp2p.utils.varint import decode_varint_with_size, encode_uvarint
from libp2p.transport.webrtc.constants import MAX_PAYLOAD_SIZE
from libp2p.transport.webrtc.pb.webrtc_pb2 import Message
from libp2p.transport.webrtc.stream import StreamState, WebRTCStream


def _framed(msg: Message) -> bytes:
    """Encode a Message in the on-wire uvarint-length-prefixed form."""
    data = msg.SerializeToString()
    return encode_uvarint(len(data)) + data


def _parse_framed(raw: bytes) -> Message:
    """Inverse of :func:`_framed` — decode the wire format back to a Message."""
    length, consumed = decode_varint_with_size(raw)
    msg = Message()
    msg.ParseFromString(raw[consumed : consumed + length])
    return msg


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
    async def test_write_sends_framed_protobuf(self):
        stream = _make_stream()
        await stream.write(b"hello")
        stream._send_callback.assert_called_once()
        raw = stream._send_callback.call_args[0][0]
        # Wire form is uvarint(len) || protobuf bytes.
        msg = _parse_framed(raw)
        assert msg.message == b"hello"
        assert not msg.HasField("flag")

    @pytest.mark.trio
    async def test_write_chunks_at_payload_size(self):
        stream = _make_stream()
        big = b"x" * (MAX_PAYLOAD_SIZE * 2)
        await stream.write(big)
        assert stream._send_callback.call_count == 2
        msg1 = _parse_framed(stream._send_callback.call_args_list[0][0][0])
        msg2 = _parse_framed(stream._send_callback.call_args_list[1][0][0])
        assert len(msg1.message) == MAX_PAYLOAD_SIZE
        assert len(msg2.message) == MAX_PAYLOAD_SIZE

    @pytest.mark.trio
    async def test_framed_message_never_exceeds_16_kib(self):
        """Every send must keep the full framed wire payload <= 16 KiB."""
        stream = _make_stream()
        await stream.write(b"y" * (MAX_PAYLOAD_SIZE * 3 + 7))
        for call in stream._send_callback.call_args_list:
            framed = call[0][0]
            assert len(framed) <= 16_384

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
        stream.on_data(_framed(Message(message=b"world")))
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
        stream.on_data(_framed(Message(message=b"abcdefgh")))
        # Read 3 bytes
        data = await stream.read(3)
        assert data == b"abc"
        # Read remaining
        data = await stream.read()
        assert data == b"defgh"

    @pytest.mark.trio
    async def test_malformed_varint_is_logged_not_raised(self):
        stream = _make_stream()
        # Five continuation bytes with no terminator is a truncated varint.
        stream.on_data(b"\xff\xff\xff\xff\xff")
        # No payload delivered.
        assert not stream._read_buf


class TestFlags:
    @pytest.mark.trio
    async def test_on_data_fin_closes_read_and_sends_fin_ack(self):
        stream = _make_stream()
        stream.on_data(_framed(Message(flag=Message.FIN)))
        assert stream._read_closed is True

    @pytest.mark.trio
    async def test_on_data_fin_ack_sets_event(self):
        stream = _make_stream()
        stream.on_data(_framed(Message(flag=Message.FIN_ACK)))
        assert stream._fin_ack_received.is_set()

    @pytest.mark.trio
    async def test_on_data_stop_sending_closes_write(self):
        stream = _make_stream()
        stream.on_data(_framed(Message(flag=Message.STOP_SENDING)))
        assert stream._write_closed is True

    @pytest.mark.trio
    async def test_on_data_reset_sets_state(self):
        stream = _make_stream()
        stream.on_data(_framed(Message(flag=Message.RESET)))
        assert stream._state == StreamState.RESET

    @pytest.mark.trio
    async def test_on_data_with_flag_and_payload(self):
        stream = _make_stream()
        stream.on_data(_framed(Message(flag=Message.FIN, message=b"last-chunk")))
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
        msg = _parse_framed(calls[0][0][0])
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
        msg = _parse_framed(calls[0][0][0])
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

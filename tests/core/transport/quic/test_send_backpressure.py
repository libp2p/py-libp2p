"""
Send-side backpressure for QUICStream.write().

aioquic's ``send_stream_data`` appends to an unbounded buffer and returns, so a
writer could "finish" gigabytes in memory long before the peer received them.
These tests exercise the watermark logic that makes write() wait for ACKs, using
a real aioquic ``QuicStream`` sender behind a mocked ``QuicConnection`` so the
buffer accounting is the real thing.
"""

from unittest.mock import Mock

import pytest
from aioquic.quic.packet_builder import QuicDeliveryState
from aioquic.quic.stream import QuicStream as AioquicStream
from multiaddr.multiaddr import Multiaddr
import trio
from trio.testing import MockClock, wait_all_tasks_blocked

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic import aioquic_compat
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.exceptions import (
    QUICStreamResetError,
    QUICStreamTimeoutError,
)
from libp2p.transport.quic.stream import QUICStream, StreamDirection

HIGH = 4096
LOW = 1024
CHUNK = 1024


def _make_connection(config: QUICTransportConfig) -> QUICConnection:
    """QUICConnection over a mocked aioquic core with real per-stream senders."""
    streams: dict[int, AioquicStream] = {}

    def send_stream_data(stream_id: int, data: bytes, end_stream: bool = False) -> None:
        stream = streams.get(stream_id)
        if stream is None:
            stream = streams[stream_id] = AioquicStream(stream_id=stream_id)
        stream.sender.write(data, end_stream=end_stream)

    mock_quic = Mock()
    mock_quic._streams = streams
    mock_quic.next_event.return_value = None
    mock_quic.datagrams_to_send.return_value = []
    mock_quic.get_timer.return_value = None
    mock_quic.send_stream_data = Mock(side_effect=send_stream_data)
    mock_quic.reset_stream = Mock()

    mock_transport = Mock()
    mock_transport._config = config

    private_key = create_new_key_pair().private_key
    peer_id = ID.from_pubkey(private_key.get_public_key())

    return QUICConnection(
        quic_connection=mock_quic,
        remote_addr=("127.0.0.1", 4001),
        remote_peer_id=None,
        local_peer_id=peer_id,
        is_initiator=True,
        maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
        transport=mock_transport,
        resource_scope=None,
        security_manager=Mock(),
    )


def _ack(connection: QUICConnection, stream_id: int, start: int, stop: int) -> None:
    """Simulate the peer acknowledging [start, stop) and run the ACK hook."""
    sender = connection._quic._streams[stream_id].sender  # type: ignore[attr-defined]
    sender.on_data_delivery(QuicDeliveryState.ACKED, start, stop, False)
    connection._refresh_send_backpressure()


@pytest.fixture
def config() -> QUICTransportConfig:
    return QUICTransportConfig(
        STREAM_SEND_BUFFER_HIGH_WATERMARK=HIGH,
        STREAM_SEND_BUFFER_LOW_WATERMARK=LOW,
        STREAM_WRITE_CHUNK_SIZE=CHUNK,
    )


@pytest.fixture
def connection(config: QUICTransportConfig) -> QUICConnection:
    return _make_connection(config)


@pytest.fixture
def stream(connection: QUICConnection) -> QUICStream:
    stream = QUICStream(
        connection=connection,
        stream_id=0,
        direction=StreamDirection.OUTBOUND,
        remote_addr=("127.0.0.1", 4001),
    )
    connection._streams[0] = stream
    return stream


# --- aioquic introspection helper -------------------------------------------


def test_stream_send_buffer_size_tracks_unacked_bytes() -> None:
    quic = Mock()
    quic._streams = {4: AioquicStream(stream_id=4)}
    sender = quic._streams[4].sender

    assert aioquic_compat.stream_send_buffer_size(quic, 4) == 0
    sender.write(b"x" * 1000)
    assert aioquic_compat.stream_send_buffer_size(quic, 4) == 1000

    # ACK the first 400 bytes: only the tail is still outstanding.
    sender.on_data_delivery(QuicDeliveryState.ACKED, 0, 400, False)
    assert aioquic_compat.stream_send_buffer_size(quic, 4) == 600

    # A loss does not shrink the buffer (data is rescheduled, not discarded).
    sender.on_data_delivery(QuicDeliveryState.LOST, 400, 700, False)
    assert aioquic_compat.stream_send_buffer_size(quic, 4) == 600

    sender.on_data_delivery(QuicDeliveryState.ACKED, 400, 1000, False)
    assert aioquic_compat.stream_send_buffer_size(quic, 4) == 0


def test_stream_send_buffer_size_is_zero_for_unknown_or_opaque_streams() -> None:
    quic = Mock()
    quic._streams = {}
    assert aioquic_compat.stream_send_buffer_size(quic, 8) == 0

    # A fully-mocked QuicConnection (no real ``_streams`` dict) must not blow up.
    assert aioquic_compat.stream_send_buffer_size(Mock(), 8) == 0


# --- config -----------------------------------------------------------------


def test_defaults_are_consistent() -> None:
    cfg = QUICTransportConfig()
    assert 0 < cfg.STREAM_SEND_BUFFER_LOW_WATERMARK
    assert cfg.STREAM_SEND_BUFFER_LOW_WATERMARK < cfg.STREAM_SEND_BUFFER_HIGH_WATERMARK
    # Do not make the local buffer tighter than the peer's flow-control window,
    # otherwise our backpressure (not QUIC flow control) caps throughput.
    assert cfg.STREAM_SEND_BUFFER_HIGH_WATERMARK >= cfg.STREAM_FLOW_CONTROL_WINDOW
    assert cfg.STREAM_WRITE_CHUNK_SIZE > 0


@pytest.mark.parametrize(
    ("low", "high", "chunk"),
    [
        (0, HIGH, CHUNK),  # low must be positive
        (HIGH, HIGH, CHUNK),  # low must be strictly below high
        (HIGH + 1, HIGH, CHUNK),  # low above high
        (LOW, HIGH, 0),  # chunk must be positive
    ],
)
def test_invalid_send_watermarks_are_rejected(low: int, high: int, chunk: int) -> None:
    with pytest.raises(ValueError):
        QUICTransportConfig(
            STREAM_SEND_BUFFER_LOW_WATERMARK=low,
            STREAM_SEND_BUFFER_HIGH_WATERMARK=high,
            STREAM_WRITE_CHUNK_SIZE=chunk,
        )


# --- write() behaviour --------------------------------------------------------


@pytest.mark.trio
async def test_small_write_does_not_block(stream: QUICStream) -> None:
    await stream.write(b"a" * (HIGH - 1))
    assert stream.send_buffer_size() == HIGH - 1
    assert stream._backpressure_event.is_set()


@pytest.mark.trio
async def test_write_blocks_at_high_watermark_and_resumes_on_ack(
    connection: QUICConnection, stream: QUICStream
) -> None:
    payload = b"b" * (2 * HIGH)
    done = False

    async def writer() -> None:
        nonlocal done
        await stream.write(payload)
        done = True

    async with trio.open_nursery() as nursery:
        nursery.start_soon(writer)
        await wait_all_tasks_blocked()

        # Exactly HIGH bytes were handed to aioquic, then the writer parked.
        assert not done
        assert stream.send_buffer_size() == HIGH
        assert not stream._backpressure_event.is_set()

        # ACKing down to (but not below) LOW+1 is not enough to resume.
        _ack(connection, 0, 0, HIGH - LOW - 1)
        await wait_all_tasks_blocked()
        assert not done
        assert stream.send_buffer_size() == LOW + 1
        assert not stream._backpressure_event.is_set()

        # Reaching LOW releases the writer, which fills up to HIGH again.
        _ack(connection, 0, HIGH - LOW - 1, HIGH - LOW)
        await wait_all_tasks_blocked()
        assert not done
        assert stream.send_buffer_size() == HIGH
        assert not stream._backpressure_event.is_set()

        # ACK everything sent so far: the remainder fits below HIGH and completes.
        sent = connection._quic._streams[0].sender._buffer_stop  # type: ignore[attr-defined]
        _ack(connection, 0, HIGH - LOW, sent)
        await wait_all_tasks_blocked()
        assert done

    total = connection._quic._streams[0].sender._buffer_stop  # type: ignore[attr-defined]
    assert total == len(payload)
    # Everything was delivered in CHUNK-sized steps.
    calls = connection._quic.send_stream_data.call_args_list  # type: ignore[attr-defined]
    assert all(len(c.args[1]) <= CHUNK for c in calls)
    assert sum(len(c.args[1]) for c in calls) == len(payload)


@pytest.mark.trio
async def test_write_times_out_when_peer_never_acks(
    config: QUICTransportConfig, autojump_clock: MockClock
) -> None:
    config.STREAM_WRITE_TIMEOUT = 5.0
    connection = _make_connection(config)
    stream = QUICStream(
        connection=connection,
        stream_id=0,
        direction=StreamDirection.OUTBOUND,
        remote_addr=("127.0.0.1", 4001),
    )
    connection._streams[0] = stream

    with pytest.raises(QUICStreamTimeoutError):
        await stream.write(b"c" * (HIGH + 1))

    # A timeout is not a protocol error: the stream must not be reset.
    assert not stream.is_reset()
    connection._quic.reset_stream.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.trio
async def test_reset_while_blocked_raises_reset_error(
    connection: QUICConnection, stream: QUICStream
) -> None:
    caught: BaseException | None = None

    async def writer() -> None:
        nonlocal caught
        try:
            await stream.write(b"d" * (HIGH + 1))
        except QUICStreamResetError as exc:
            caught = exc

    async with trio.open_nursery() as nursery:
        nursery.start_soon(writer)
        await wait_all_tasks_blocked()
        assert not stream._backpressure_event.is_set()
        await stream.handle_reset(error_code=7)

    assert isinstance(caught, QUICStreamResetError)
    assert caught.error_code == 7


@pytest.mark.trio
async def test_refresh_only_releases_when_buffer_drained(
    connection: QUICConnection, stream: QUICStream
) -> None:
    """The connection-side hook must not release a still-full stream."""
    await stream.write(b"e" * HIGH)
    assert not stream._backpressure_event.is_set()

    connection._refresh_send_backpressure()
    assert not stream._backpressure_event.is_set()

    _ack(connection, 0, 0, HIGH)
    assert stream._backpressure_event.is_set()


@pytest.mark.trio
async def test_closed_stream_never_keeps_writers_blocked(stream: QUICStream) -> None:
    await stream.write(b"f" * HIGH)
    assert not stream._backpressure_event.is_set()

    # Once our write side is closed there is nothing left to wait for.
    await stream.close_write()
    stream._update_send_backpressure()
    assert stream._backpressure_event.is_set()

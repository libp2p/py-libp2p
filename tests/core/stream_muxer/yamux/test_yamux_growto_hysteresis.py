"""
Unit tests for Go-like GrowTo hysteresis and pending recv release batching.
"""

import os
from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.stream_muxer.yamux.yamux import (
    DEFAULT_WINDOW_SIZE,
    MAX_WINDOW_SIZE,
    YamuxStream,
)

PERF_CHUNK = 65500  # legacy interop perf read size
READ_CHUNK = 64 * 1024  # two reads cross half-window (131072)
HALF_WINDOW = DEFAULT_WINDOW_SIZE // 2

_PY_YAMUX_ENV_KEYS = (
    "PY_YAMUX_DISABLE_HYSTERESIS",
    "PY_YAMUX_RELEASE_ON_READ",
    "PY_YAMUX_ASSUME_RTT_MS",
    "PY_YAMUX_BATCH_THRESHOLD_DIV",
    "PY_YAMUX_DEBUG",
)


def _clear_py_yamux_env() -> None:
    for key in _PY_YAMUX_ENV_KEYS:
        os.environ.pop(key, None)


def _make_stream(
    *,
    recv_window: int = DEFAULT_WINDOW_SIZE,
    target_recv_window: int = DEFAULT_WINDOW_SIZE,
    buffered: int = 0,
    rtt: float = 0.0,
) -> tuple[YamuxStream, AsyncMock]:
    mock_conn = Mock()
    mock_conn.stream_buffers = {1: bytearray(b"x" * buffered)}
    mock_conn.rtt = Mock(return_value=rtt)
    mock_conn._write_frame = AsyncMock()
    stream = YamuxStream(1, mock_conn, is_initiator=True)
    stream.recv_window = recv_window
    stream.target_recv_window = target_recv_window
    send_update = AsyncMock()
    stream.send_window_update = send_update
    return stream, send_update


@pytest.mark.trio
async def test_release_on_read_sends_credit_when_hysteresis_defers_grow() -> None:
    """Single read below half-window sends at least per-read credit (default)."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "1"
    stream, send_update = _make_stream()
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    call = send_update.await_args
    assert call is not None
    assert call.args[0] >= PERF_CHUNK
    assert stream._pending_recv_release == 0


@pytest.mark.trio
async def test_autotune_on_release_doubles_target() -> None:
    """Branch C runs auto-tune when effective RTT is available."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "1"
    stream, send_update = _make_stream(rtt=0.001)
    stream.epoch_start = 0.0
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    call = send_update.await_args
    assert call is not None
    assert call.args[0] > PERF_CHUNK
    assert stream.target_recv_window == 2 * DEFAULT_WINDOW_SIZE


@pytest.mark.trio
async def test_partial_slack_includes_autotune_extra() -> None:
    """Partial slack branch reclaims delta and may add auto-tune increment."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "0"
    slack = HALF_WINDOW // 2
    stream, send_update = _make_stream(
        recv_window=DEFAULT_WINDOW_SIZE - slack - PERF_CHUNK,
        buffered=0,
        rtt=0.001,
    )
    stream.epoch_start = 0.0
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    call = send_update.await_args
    assert call is not None
    assert call.args[0] >= slack + PERF_CHUNK
    assert stream._window_update_partial_slack == 1


@pytest.mark.trio
async def test_pending_flush_after_two_reads() -> None:
    """Two 64KiB reads batch into one >= half-window WINDOW_UPDATE."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "0"
    stream, send_update = _make_stream()
    await stream._auto_tune_and_send_window_update(bytes_read=READ_CHUNK)
    assert send_update.await_count == 0
    assert stream._pending_recv_release == READ_CHUNK

    await stream._auto_tune_and_send_window_update(bytes_read=READ_CHUNK)
    send_update.assert_awaited_once()
    call = send_update.await_args
    assert call is not None
    assert call.args[0] >= HALF_WINDOW
    assert stream._window_update_pending_flush == 1


@pytest.mark.trio
async def test_full_grow_when_delta_exceeds_threshold() -> None:
    """Large gap to target triggers full GrowTo (branch A)."""
    _clear_py_yamux_env()
    stream, send_update = _make_stream(
        recv_window=0,
        target_recv_window=DEFAULT_WINDOW_SIZE,
        buffered=0,
    )
    await stream._auto_tune_and_send_window_update(bytes_read=0)
    send_update.assert_awaited_once()
    call = send_update.await_args
    assert call is not None
    assert call.args[0] >= HALF_WINDOW
    assert stream._window_update_full_grow == 1
    assert stream._pending_recv_release == 0


@pytest.mark.trio
async def test_disable_hysteresis_forces_full_grow() -> None:
    """PY_YAMUX_DISABLE_HYSTERESIS sends large update on small positive delta."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_DISABLE_HYSTERESIS"] = "1"
    stream, send_update = _make_stream(
        recv_window=DEFAULT_WINDOW_SIZE - PERF_CHUNK,
        target_recv_window=DEFAULT_WINDOW_SIZE,
        buffered=0,
    )
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    call = send_update.await_args
    assert call is not None
    assert call.args[0] >= PERF_CHUNK


@pytest.mark.trio
async def test_assume_rtt_ms_enables_autotune_without_ping() -> None:
    """PY_YAMUX_ASSUME_RTT_MS bootstraps auto-tune when conn.rtt() is zero."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_ASSUME_RTT_MS"] = "1"
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "1"
    stream, send_update = _make_stream(rtt=0.0)
    stream.epoch_start = 0.0
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    assert stream.target_recv_window > DEFAULT_WINDOW_SIZE
    assert stream.target_recv_window <= MAX_WINDOW_SIZE


@pytest.mark.trio
async def test_default_assume_rtt_bootstrap_without_env() -> None:
    """When PY_YAMUX_ASSUME_RTT_MS is unset, default 1ms bootstrap enables autotune."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "1"
    stream, send_update = _make_stream(rtt=0.0)
    stream.epoch_start = 0.0
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    assert stream.target_recv_window > DEFAULT_WINDOW_SIZE


@pytest.mark.trio
async def test_assume_rtt_zero_disables_autotune_bootstrap() -> None:
    """Explicit PY_YAMUX_ASSUME_RTT_MS=0 disables bootstrap when ping RTT is zero."""
    _clear_py_yamux_env()
    os.environ["PY_YAMUX_ASSUME_RTT_MS"] = "0"
    os.environ["PY_YAMUX_RELEASE_ON_READ"] = "1"
    stream, send_update = _make_stream(rtt=0.0)
    stream.epoch_start = 0.0
    await stream._auto_tune_and_send_window_update(bytes_read=PERF_CHUNK)
    send_update.assert_awaited_once()
    assert stream.target_recv_window == DEFAULT_WINDOW_SIZE

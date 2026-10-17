"""Unit tests for expected connection-shutdown detection."""

from __future__ import annotations

import pytest

try:
    ExceptionGroup  # noqa: B018
except NameError:
    from exceptiongroup import ExceptionGroup  # type: ignore[no-redef]

from libp2p.network.connection.exceptions import RawConnError
from libp2p.stream_muxer.exceptions import MuxedConnUnavailable
from libp2p.utils.connection_shutdown import (
    is_expected_connection_shutdown,
    log_expected_connection_shutdown,
)


def test_expected_muxed_conn_unavailable() -> None:
    assert is_expected_connection_shutdown(MuxedConnUnavailable("Connection closed"))


def test_expected_phrases() -> None:
    assert is_expected_connection_shutdown(RuntimeError("connection closed"))
    assert is_expected_connection_shutdown(RuntimeError("TLS connection is closed"))
    assert is_expected_connection_shutdown(RuntimeError("broken pipe"))


def test_empty_raw_conn_error_is_expected() -> None:
    assert is_expected_connection_shutdown(RawConnError())


def test_unrelated_error_not_expected() -> None:
    assert not is_expected_connection_shutdown(RuntimeError("negotiation failed"))
    assert not is_expected_connection_shutdown(None)


def test_exception_group_all_expected() -> None:
    eg = ExceptionGroup(
        "shutdown",
        [RuntimeError("connection closed"), RuntimeError("stream eof")],
    )
    assert is_expected_connection_shutdown(eg)


def test_exception_group_mixed_not_expected() -> None:
    mixed = ExceptionGroup(
        "shutdown",
        [RuntimeError("connection closed"), RuntimeError("other failure")],
    )
    assert not is_expected_connection_shutdown(mixed)


def test_cause_chain() -> None:
    cause = RuntimeError("connection reset")
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = cause
    assert is_expected_connection_shutdown(wrapper)


def test_log_expected_emits_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[str] = []

    def _capture(msg: str, *args: object, **_kwargs: object) -> None:
        recorded.append(msg % args if args else msg)

    monkeypatch.setattr(
        "libp2p.utils.connection_shutdown.logger.debug",
        _capture,
    )
    log_expected_connection_shutdown(
        component="test",
        peer_id="peer",
        direction="remote",
        exc=MuxedConnUnavailable("Connection closed"),
    )
    assert recorded
    assert "expected connection shutdown" in recorded[0]

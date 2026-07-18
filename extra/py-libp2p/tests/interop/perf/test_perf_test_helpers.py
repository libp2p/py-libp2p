"""Unit tests for interop/perf/perf_test.py helper logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import multiaddr

pytest.importorskip("redis")

try:
    ExceptionGroup  # noqa: B018
except NameError:
    from exceptiongroup import ExceptionGroup  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PERF_TEST_PATH = _REPO_ROOT / "interop" / "perf" / "perf_test.py"


def _load_perf_test_module():
    spec = importlib.util.spec_from_file_location("interop_perf_test", _PERF_TEST_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["interop_perf_test"] = module
    spec.loader.exec_module(module)
    return module


perf_test = _load_perf_test_module()

_is_connection_closed_error = perf_test._is_connection_closed_error
_env_int = perf_test._env_int
_env_float = perf_test._env_float
PerfTest = perf_test.PerfTest


def _perf_test_env(
    monkeypatch: pytest.MonkeyPatch, *, is_dialer: bool, tmp_path: Path
) -> PerfTest:
    monkeypatch.setenv("TRANSPORT", "tcp")
    monkeypatch.setenv("MUXER", "mplex")
    monkeypatch.setenv("SECURE_CHANNEL", "tls")
    monkeypatch.setenv("IS_DIALER", "true" if is_dialer else "false")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("PERF_LOCAL_ADDR_FILE", str(tmp_path / "perf-local-addr"))
    monkeypatch.delenv("REDIS_ADDR", raising=False)
    return PerfTest()


def test_is_connection_closed_error_matching_phrases() -> None:
    assert _is_connection_closed_error(RuntimeError("connection closed"))
    assert _is_connection_closed_error(RuntimeError("TLS connection is closed"))
    assert _is_connection_closed_error(RuntimeError("broken pipe"))


def test_is_connection_closed_error_unrelated() -> None:
    assert not _is_connection_closed_error(RuntimeError("negotiation failed"))
    assert not _is_connection_closed_error(None)


def test_is_connection_closed_error_exception_group() -> None:
    eg = ExceptionGroup(
        "shutdown",
        [RuntimeError("connection closed"), RuntimeError("stream eof")],
    )
    assert _is_connection_closed_error(eg)

    mixed = ExceptionGroup(
        "shutdown",
        [RuntimeError("connection closed"), RuntimeError("other failure")],
    )
    assert not _is_connection_closed_error(mixed)


def test_is_connection_closed_error_cause_chain() -> None:
    cause = RuntimeError("connection reset")
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = cause
    assert _is_connection_closed_error(wrapper)


def test_should_ignore_shutdown_error_dialer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    test = _perf_test_env(monkeypatch, is_dialer=True, tmp_path=tmp_path)
    exc = RuntimeError("connection closed")

    test._benchmarks_complete = False
    assert not test._should_ignore_shutdown_error(exc)

    test._benchmarks_complete = True
    assert test._should_ignore_shutdown_error(exc)


def test_should_ignore_shutdown_error_listener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    test = _perf_test_env(monkeypatch, is_dialer=False, tmp_path=tmp_path)
    exc = RuntimeError("connection closed")

    test._listener_served_peer = False
    assert not test._should_ignore_shutdown_error(exc)

    test._listener_served_peer = True
    assert test._should_ignore_shutdown_error(exc)


def test_should_ignore_shutdown_error_non_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    test = _perf_test_env(monkeypatch, is_dialer=True, tmp_path=tmp_path)
    test._benchmarks_complete = True
    assert not test._should_ignore_shutdown_error(RuntimeError("timeout"))


def test_env_int_defaults_and_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_ENV_INT", raising=False)
    assert _env_int("TEST_ENV_INT", 42) == 42
    monkeypatch.setenv("TEST_ENV_INT", "not-a-number")
    assert _env_int("TEST_ENV_INT", 42) == 42
    monkeypatch.setenv("TEST_ENV_INT", "5")
    assert _env_int("TEST_ENV_INT", 42, minimum=10) == 10


def test_env_float_defaults_and_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_ENV_FLOAT", raising=False)
    assert _env_float("TEST_ENV_FLOAT", 1.5) == 1.5
    monkeypatch.setenv("TEST_ENV_FLOAT", "bad")
    assert _env_float("TEST_ENV_FLOAT", 1.5) == 1.5
    monkeypatch.setenv("TEST_ENV_FLOAT", "0.1")
    assert _env_float("TEST_ENV_FLOAT", 1.5, minimum=1.0) == 1.0


def test_listener_teardown_idle_secs_ws_mplex(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRANSPORT", "ws")
    monkeypatch.setenv("MUXER", "mplex")
    monkeypatch.setenv("SECURE_CHANNEL", "noise")
    monkeypatch.setenv("IS_DIALER", "false")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("PERF_LOCAL_ADDR_FILE", str(tmp_path / "perf-local-addr"))
    monkeypatch.delenv("REDIS_ADDR", raising=False)
    test = PerfTest()
    assert test._listener_teardown_idle_secs() == 30.0


def test_listener_teardown_idle_secs_tcp_yamux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRANSPORT", "tcp")
    monkeypatch.setenv("MUXER", "yamux")
    monkeypatch.setenv("SECURE_CHANNEL", "noise")
    monkeypatch.setenv("IS_DIALER", "false")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("PERF_LOCAL_ADDR_FILE", str(tmp_path / "perf-local-addr"))
    monkeypatch.delenv("REDIS_ADDR", raising=False)
    test = PerfTest()
    assert test._listener_teardown_idle_secs() == 1.5


def test_without_loopback_listen_addrs_filters_loopback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRANSPORT", "ws")
    monkeypatch.setenv("MUXER", "mplex")
    monkeypatch.setenv("SECURE_CHANNEL", "noise")
    monkeypatch.setenv("IS_DIALER", "true")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("PERF_LOCAL_ADDR_FILE", str(tmp_path / "perf-local-addr"))
    monkeypatch.delenv("REDIS_ADDR", raising=False)
    test = PerfTest()
    addrs = [
        multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
        multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/0/ws"),
    ]
    filtered = test._without_loopback_listen_addrs(addrs)
    assert len(filtered) == 1
    assert "192.168.1.1" in str(filtered[0])


def test_connection_config_denies_loopback_and_disables_autoconnect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRANSPORT", "tcp")
    monkeypatch.setenv("MUXER", "yamux")
    monkeypatch.setenv("SECURE_CHANNEL", "noise")
    monkeypatch.setenv("IS_DIALER", "true")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("PERF_LOCAL_ADDR_FILE", str(tmp_path / "perf-local-addr"))
    monkeypatch.delenv("REDIS_ADDR", raising=False)
    cfg = PerfTest()._connection_config()
    assert cfg.min_connections == 0
    assert cfg.low_watermark == 0
    assert "127.0.0.0/8" in cfg.deny_list

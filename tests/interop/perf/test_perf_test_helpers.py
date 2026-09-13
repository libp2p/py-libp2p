"""Unit tests for interop/perf/perf_test.py helper logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import multiaddr

pytest.importorskip("redis")

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

_env_int = perf_test._env_int
_env_float = perf_test._env_float
PerfTest = perf_test.PerfTest


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

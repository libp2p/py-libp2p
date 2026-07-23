"""Unit tests for interop/transport/ping_test.py helper logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import multiaddr

pytest.importorskip("redis")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PING_TEST_PATH = _REPO_ROOT / "interop" / "transport" / "ping_test.py"


def _load_ping_test_module():
    import sys
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import interop.transport.ping_test as ping_test_mod
    return ping_test_mod


ping_test = _load_ping_test_module()
PingTest = ping_test.PingTest


def _ping_test_env(monkeypatch: pytest.MonkeyPatch) -> PingTest:
    monkeypatch.setenv("TRANSPORT", "tcp")
    monkeypatch.setenv("MUXER", "mplex")
    monkeypatch.setenv("SECURE_CHANNEL", "noise")
    monkeypatch.setenv("IS_DIALER", "false")
    monkeypatch.setenv("LISTENER_IP", "0.0.0.0")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("REDIS_ADDR", "redis:6379")
    return PingTest()


@pytest.mark.parametrize(
    ("addr_str", "expected"),
    [
        ("/ip6/::1/tcp/46499", "::1"),
        ("/ip4/127.0.0.1/tcp/8080", "127.0.0.1"),
        ("/tcp/8080", None),
    ],
)
def test_get_ip_value(
    monkeypatch: pytest.MonkeyPatch,
    addr_str: str,
    expected: str | None,
) -> None:
    test = _ping_test_env(monkeypatch)
    addr = multiaddr.Multiaddr(addr_str)
    assert test._get_ip_value(addr) == expected

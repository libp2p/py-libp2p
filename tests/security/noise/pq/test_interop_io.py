"""
Bounds tests for the interop harness I/O helpers (harness audit F-001/F-002).

``scripts/_interop_io.py`` is loaded by path because ``scripts/`` is not a
package; the harnesses themselves reach it via their own directory being on
``sys.path``.

The harnesses run on asyncio while this test suite runs in trio mode, so each
test is a plain synchronous function that drives the coroutine under test with
``asyncio.run``.
"""

import asyncio
import importlib.util
import pathlib
import sys
import types

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_INTEROP_IO = _REPO_ROOT / "scripts" / "_interop_io.py"

# A reader with no cap would spin here forever; this makes that fail loudly
# instead of hanging the suite.
_FLOOD_READ_LIMIT = 100


def _load_interop_io() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_interop_io_under_test", _INTEROP_IO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


interop_io = _load_interop_io()


class _FloodingSession:
    """A peer that streams newline-free data, as a hostile peer would."""

    def __init__(self, chunk: bytes = b"A" * 4096) -> None:
        self._chunk = chunk
        self.reads = 0

    async def read(self, n: int | None = None) -> bytes:
        self.reads += 1
        if self.reads > _FLOOD_READ_LIMIT:
            raise AssertionError(
                f"read_greeting accumulated {self.reads} chunks without a cap"
            )
        return self._chunk


class _PoliteSession:
    """A peer that sends one well-formed greeting."""

    def __init__(self) -> None:
        self._chunks = [b"hello from Nim\n"]

    async def read(self, n: int | None = None) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def test_read_greeting_caps_the_accumulated_buffer() -> None:
    """
    A peer that never sends a newline must not grow the buffer without bound.

    Nim already behaves this way: it reads exactly one framed message and
    raises "truncated greeting" if that frame has no newline.
    """
    session = _FloodingSession()

    with pytest.raises(ValueError, match="truncated greeting"):
        asyncio.run(interop_io.read_greeting(session))

    assert session.reads <= 2, "should give up as soon as the cap is passed"


def test_read_greeting_accepts_a_normal_greeting() -> None:
    assert asyncio.run(interop_io.read_greeting(_PoliteSession())) == "hello from Nim"


def test_with_deadline_gives_up_on_a_silent_peer() -> None:
    """A silent peer must not pin the harness forever."""

    async def never_finishes() -> None:
        await asyncio.sleep(3600)

    async def drive() -> None:
        await interop_io.with_deadline(never_finishes(), "test phase", timeout=0.05)

    with pytest.raises(TimeoutError, match="test phase"):
        asyncio.run(drive())


def test_with_deadline_passes_a_result_through() -> None:
    async def quick() -> str:
        return "done"

    async def drive() -> str:
        result: str = await interop_io.with_deadline(quick(), "test phase", timeout=5.0)
        return result

    assert asyncio.run(drive()) == "done"


def test_overall_timeout_is_defined_and_generous() -> None:
    """
    The runner bounds the dialer at 60 s; the harnesses must outlast that so a
    standalone deadline never turns a slow but healthy run into a failure.
    """
    assert interop_io.OVERALL_TIMEOUT_SECONDS >= 60.0

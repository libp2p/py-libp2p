"""
Regression tests for _aiortc_helpers.run_signaling_server hardening.

Covers the acceptance criteria from issue #1354:
  - Content-Length > _MAX_SDP_BODY_SIZE  → 413, no body buffer allocated
  - Non-integer / negative Content-Length → 400
  - Header loop exceeds _MAX_HEADER_LINES or _MAX_HEADER_BYTES → 400
  - Happy path still returns 200

All tests are sync wrappers over asyncio coroutines so they run outside
trio_mode and don't interfere with the project-wide trio backend.
"""
# pyrefly: ignore

from __future__ import annotations

import asyncio
import sys

import pytest

try:
    from libp2p.transport.webrtc._aiortc_helpers import (
        _MAX_HEADER_BYTES,
        _MAX_HEADER_LINES,
        _MAX_SDP_BODY_SIZE,
        run_signaling_server,
    )

    HAS_AIORTC = True
except ImportError:
    HAS_AIORTC = False

pytestmark = pytest.mark.skipif(not HAS_AIORTC, reason="aiortc not installed")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _start(on_offer=None):
    """Start the signaling server on a free port; return (server, port)."""
    if on_offer is None:

        async def on_offer(sdp: str) -> str:
            return "v=0\r\n"

    server = await run_signaling_server("127.0.0.1", 0, on_offer)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _status(port: int, raw_request: bytes, timeout: float = 5.0) -> bytes:
    """Send *raw_request* and return the HTTP status line."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(raw_request)
        await writer.drain()
        return await asyncio.wait_for(reader.readline(), timeout=timeout)
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Content-Length validation
# ---------------------------------------------------------------------------


class TestContentLength:
    def test_too_large_returns_413_and_no_rss_spike(self) -> None:
        asyncio.run(self._too_large())

    async def _too_large(self) -> None:
        # Snapshot RSS high-water mark before the request.
        try:
            import resource

            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except ImportError:
            rss_before = None

        server, port = await _start()
        try:
            line = await _status(
                port,
                b"POST /sdp HTTP/1.1\r\nContent-Length: 999999999\r\n\r\n",
            )
            assert b"413" in line
        finally:
            server.close()
            await server.wait_closed()

        # Soft RSS check: the body buffer (≈1 GiB) must NOT have been allocated.
        # ru_maxrss is the high-water mark so a delta > 0 means new peak memory.
        if rss_before is not None:
            import resource

            rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            delta = rss_after - rss_before
            # Linux: ru_maxrss in KiB; macOS: in bytes
            one_mib = 1024 if sys.platform.startswith("linux") else 1024 * 1024
            assert delta < one_mib, (
                f"RSS high-water grew by {delta} units after 413 rejection; "
                "body buffer may have been allocated before the check"
            )

    def test_non_integer_returns_400(self) -> None:
        asyncio.run(self._non_integer())

    async def _non_integer(self) -> None:
        server, port = await _start()
        try:
            line = await _status(
                port,
                b"POST /sdp HTTP/1.1\r\nContent-Length: notanumber\r\n\r\n",
            )
            assert b"400" in line
        finally:
            server.close()
            await server.wait_closed()

    def test_negative_returns_400(self) -> None:
        asyncio.run(self._negative())

    async def _negative(self) -> None:
        server, port = await _start()
        try:
            line = await _status(
                port,
                b"POST /sdp HTTP/1.1\r\nContent-Length: -1\r\n\r\n",
            )
            assert b"400" in line
        finally:
            server.close()
            await server.wait_closed()

    def test_exactly_at_limit_is_accepted(self) -> None:
        asyncio.run(self._at_limit())

    async def _at_limit(self) -> None:
        body = b"x" * _MAX_SDP_BODY_SIZE

        async def on_offer(sdp: str) -> str:
            return "v=0\r\n"

        server, port = await _start(on_offer)
        try:
            request = (
                b"POST /sdp HTTP/1.1\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"\r\n" + body
            )
            line = await _status(port, request)
            assert b"200" in line
        finally:
            server.close()
            await server.wait_closed()


# ---------------------------------------------------------------------------
# Header loop bounds
# ---------------------------------------------------------------------------


class TestHeaderBounds:
    def test_too_many_header_lines_returns_400(self) -> None:
        asyncio.run(self._too_many_lines())

    async def _too_many_lines(self) -> None:
        # Send _MAX_HEADER_LINES + 1 non-blank headers — the loop must reject
        # before ever reaching the blank-line terminator.
        spam = b"".join(
            f"X-Spam-{i}: v\r\n".encode() for i in range(_MAX_HEADER_LINES + 1)
        )
        server, port = await _start()
        try:
            line = await _status(port, b"POST /sdp HTTP/1.1\r\n" + spam + b"\r\n")
            assert b"400" in line
        finally:
            server.close()
            await server.wait_closed()

    def test_header_bytes_over_limit_returns_400(self) -> None:
        asyncio.run(self._too_many_bytes())

    async def _too_many_bytes(self) -> None:
        # A single header line that exceeds _MAX_HEADER_BYTES.
        big = b"X-Big: " + b"x" * (_MAX_HEADER_BYTES + 1) + b"\r\n"
        server, port = await _start()
        try:
            line = await _status(port, b"POST /sdp HTTP/1.1\r\n" + big + b"\r\n")
            assert b"400" in line
        finally:
            server.close()
            await server.wait_closed()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_request_returns_200(self) -> None:
        asyncio.run(self._valid())

    async def _valid(self) -> None:
        received: list[str] = []

        async def on_offer(sdp: str) -> str:
            received.append(sdp)
            return "v=0\r\nanswer"

        server, port = await _start(on_offer)
        body = b"v=0\r\noffer"
        try:
            request = (
                b"POST /sdp HTTP/1.1\r\n"
                b"Content-Type: application/sdp\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"\r\n" + body
            )
            line = await _status(port, request)
            assert b"200" in line
            assert received == ["v=0\r\noffer"]
        finally:
            server.close()
            await server.wait_closed()

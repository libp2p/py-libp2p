"""Shared fixtures and mocks for perf protocol tests."""

import pytest

from libp2p.perf import PerfService


class MockNetStream:
    """Mock stream for testing server handler in isolation."""

    def __init__(
        self,
        data_to_read: bytes,
        *,
        raise_on_read: bool = False,
        close_after_bytes: int | None = None,
        raise_after_bytes: int | None = None,
    ):
        self._read_buffer = data_to_read
        self._write_buffer = b""
        self._reset_called = False
        self._closed = False
        self._raise_on_read = raise_on_read
        self._close_after_bytes = close_after_bytes
        self._raise_after_bytes = raise_after_bytes
        self._bytes_read = 0

    async def read(self, n: int) -> bytes:
        if self._raise_on_read:
            raise ConnectionError("Mock read error")

        if self._raise_after_bytes is not None:
            if self._bytes_read >= self._raise_after_bytes:
                raise ConnectionError("Mock read error after bytes")

        if self._close_after_bytes is not None:
            if self._bytes_read >= self._close_after_bytes:
                return b""

        chunk = self._read_buffer[:n]
        self._read_buffer = self._read_buffer[n:]
        self._bytes_read += len(chunk)
        return chunk

    async def write(self, data: bytes) -> None:
        self._write_buffer += data

    async def reset(self) -> None:
        self._reset_called = True

    async def close(self) -> None:
        self._closed = True


class MockHost:
    """Minimal mock host for PerfService initialization."""

    def set_stream_handler(self, protocol, handler):
        pass


@pytest.fixture
def mock_host():
    """Provide a mock host for testing."""
    return MockHost()


@pytest.fixture
def perf_service(mock_host):
    """Provide a PerfService instance for testing."""
    return PerfService(mock_host)

"""Tests for RawConnection error handling."""

import pytest

from libp2p.io.abc import ReadWriteCloser
from libp2p.network.connection.exceptions import RawConnError
from libp2p.network.connection.raw_connection import RawConnection


class MockStreamRaisesConnectionReset(ReadWriteCloser):
    """A mock stream that always raises ConnectionResetError on read/write."""

    async def read(self, n: int | None = None) -> bytes:
        raise ConnectionResetError("Connection reset by peer")

    async def write(self, data: bytes) -> None:
        raise ConnectionResetError("Connection reset by peer")

    async def close(self) -> None:
        pass

    def get_remote_address(self) -> tuple[str, int]:
        return ("127.0.0.1", 1234)


@pytest.mark.trio
async def test_raw_connection_handles_connection_reset_error_on_read():
    """RawConnection.read() must wrap ConnectionResetError into RawConnError."""
    conn = RawConnection(MockStreamRaisesConnectionReset(), initiator=True)
    with pytest.raises(RawConnError):
        await conn.read(10)


@pytest.mark.trio
async def test_raw_connection_handles_connection_reset_error_on_write():
    """RawConnection.write() must wrap ConnectionResetError into RawConnError."""
    conn = RawConnection(MockStreamRaisesConnectionReset(), initiator=True)
    with pytest.raises(RawConnError):
        await conn.write(b"hello")

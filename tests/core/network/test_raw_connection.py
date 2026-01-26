
import pytest
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.connection.exceptions import RawConnError
from libp2p.io.abc import ReadWriteCloser

class MockInternalStream(ReadWriteCloser):
    async def read(self, n: int | None = None) -> bytes:
        raise ConnectionResetError("Connection reset")

    async def write(self, data: bytes) -> None:
        raise ConnectionResetError("Connection reset")

    async def close(self) -> None:
        pass

    def get_remote_address(self):
        return ("127.0.0.1", 1234)

@pytest.mark.trio
async def test_raw_connection_handles_connection_reset_error_on_read():
    """
    Test that RawConnection catches ConnectionResetError and raises RawConnError on read.
    """
    stream = MockInternalStream()
    conn = RawConnection(stream, True)
    
    with pytest.raises(RawConnError):
        await conn.read(10)

@pytest.mark.trio
async def test_raw_connection_handles_connection_reset_error_on_write():
    """
    Test that RawConnection catches ConnectionResetError and raises RawConnError on write.
    """
    stream = MockInternalStream()
    conn = RawConnection(stream, True)
    
    with pytest.raises(RawConnError):
        await conn.write(b"data")

import pytest
import trio

from libp2p.io.abc import ReadWriteCloser
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.security.pnet.protector import new_protected_conn


# --- MemoryPipe: implements ReadWriteCloser interface ---
class MemoryPipe(ReadWriteCloser):
    """Wrap a pair of Trio memory channels into a ReadWriteCloser-like object."""

    def __init__(
        self, send: trio.MemorySendChannel, receive: trio.MemoryReceiveChannel
    ):
        self._send = send
        self._receive = receive

    async def read(self, n: int | None = None) -> bytes:
        """Read next chunk from receive channel."""
        return await self._receive.receive()

    async def write(self, data: bytes) -> None:
        """Write a chunk to send channel."""
        await self._send.send(data)

    async def close(self) -> None:
        """Close channels (noop for memory channels)."""
        pass

    def get_remote_address(self) -> tuple[str, int] | None:
        # Memory pipe doesn’t have a real address, so return None
        return None


# --- Helper function to create a connected pair of PskConns ---
async def make_psk_pair(psk_hex: str):
    send1, recv1 = trio.open_memory_channel(0)
    send2, recv2 = trio.open_memory_channel(0)

    pipe1 = MemoryPipe(send1, recv2)
    pipe2 = MemoryPipe(send2, recv1)

    raw1 = RawConnection(pipe1, False)
    raw2 = RawConnection(pipe2, False)

    # NOTE: The new_protected_conn function needs to perform the handshake.
    # We'll assume it does for this example. If not, a handshake() call
    # might be needed here within a nursery.
    psk_conn1 = new_protected_conn(raw1, psk_hex)
    psk_conn2 = new_protected_conn(raw2, psk_hex)

    return psk_conn1, psk_conn2


@pytest.mark.trio
async def test_psk_simple_message():
    # Use a fixed PSK for testing
    psk_hex = "dffb7e3135399a8b1612b2aaca1c36a3a8ac2cd0cca51ceeb2ced87d308cac6d"
    conn1, conn2 = await make_psk_pair(psk_hex)

    msg = b"hello world"

    async with trio.open_nursery() as nursery:
        nursery.start_soon(conn1.write, msg)
        received = await conn2.read(len(msg))

    assert received == msg, "Decrypted message does not match original"


@pytest.mark.trio
async def test_psk_empty_message():
    # PSK for testing
    psk_hex = "dffb7e3135399a8b1612b2aaca1c36a3a8ac2cd0cca51ceeb2ced87d308cac6d"
    conn1, conn2 = await make_psk_pair(psk_hex)

    # Empty message should round-trip correctly
    async with trio.open_nursery() as nursery:
        nursery.start_soon(conn1.write, b"")
        received = await conn2.read(0)

    assert received == b"", "Empty message failed"

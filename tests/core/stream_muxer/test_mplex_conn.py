from unittest.mock import (
    Mock,
)

import pytest
import trio

from libp2p.abc import ISecureConn
from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.peer.id import ID
from libp2p.stream_muxer.mplex.mplex import (
    Mplex,
)

DUMMY_PEER_ID = ID(b"dummy_peer_id")


class DummySecuredConn(ISecureConn):
    def __init__(self, is_initiator: bool = False):
        self.is_initiator = is_initiator

    async def write(self, data: bytes) -> None:
        pass

    async def read(self, n: int | None = -1) -> bytes:
        return b""

    async def close(self) -> None:
        pass

    def get_remote_address(self):
        return None

    def get_local_address(self):
        return None

    def get_local_peer(self) -> ID:
        return ID(b"local")

    def get_local_private_key(self) -> PrivateKey:
        return Mock(spec=PrivateKey)  # Dummy key

    def get_remote_peer(self) -> ID:
        return DUMMY_PEER_ID

    def get_remote_public_key(self) -> PublicKey:
        return Mock(spec=PublicKey)  # Dummy key


@pytest.mark.trio
async def test_mplex_conn(mplex_conn_pair):
    conn_0, conn_1 = mplex_conn_pair

    assert len(conn_0.streams) == 0
    assert len(conn_1.streams) == 0

    # Test: Open a stream, and both side get 1 more stream.
    stream_0 = await conn_0.open_stream()
    await trio.sleep(0.1)
    assert len(conn_0.streams) == 1
    assert len(conn_1.streams) == 1
    # Test: From another side.
    stream_1 = await conn_1.open_stream()
    await trio.sleep(0.1)
    assert len(conn_0.streams) == 2
    assert len(conn_1.streams) == 2

    # Close from one side.
    await conn_0.close()
    # Sleep for a while for both side to handle `close`.
    await trio.sleep(0.1)
    # Test: Both side is closed.
    assert conn_0.is_closed
    assert conn_1.is_closed
    # Test: All streams should have been closed.
    assert stream_0.event_remote_closed.is_set()
    assert stream_0.event_reset.is_set()
    assert stream_0.event_local_closed.is_set()
    # Test: All streams on the other side are also closed.
    assert stream_1.event_remote_closed.is_set()
    assert stream_1.event_reset.is_set()
    assert stream_1.event_local_closed.is_set()

    # Test: No effect to close more than once between two side.
    await conn_0.close()
    await conn_1.close()


@pytest.mark.trio
async def test_mplex_on_close_callback():
    """Test that on_close callback is called when Mplex connection is closed."""
    # Create a mock on_close callback
    on_close_called = trio.Event()
    callback_called_count = [0]  # Use list to make it mutable

    async def on_close_callback() -> None:
        callback_called_count[0] += 1
        on_close_called.set()

    # Create Mplex connection with on_close callback
    secured_conn = DummySecuredConn()
    mplex_conn = Mplex(secured_conn, DUMMY_PEER_ID, on_close=on_close_callback)

    # Start the connection to initialize it
    async with trio.open_nursery() as nursery:
        nursery.start_soon(mplex_conn.start)

        # Wait a bit for connection to start
        await trio.sleep(0.1)

        # Close the connection
        await mplex_conn.close()

        # Wait for cleanup to complete and callback to be called
        with trio.move_on_after(1.0):  # 1 second timeout
            await on_close_called.wait()

        # Cancel the nursery to stop the start() task
        nursery.cancel_scope.cancel()

    # Verify callback was called exactly once
    assert callback_called_count[0] == 1, (
        "on_close callback should be called exactly once"
    )
    assert on_close_called.is_set(), "on_close callback should have been invoked"
    assert mplex_conn.is_closed, "Connection should be marked as closed"


@pytest.mark.trio
async def test_mplex_on_close_callback_with_error():
    """Test that errors in on_close callback are handled gracefully."""
    # Create a mock on_close callback that raises an error
    error_raised = False

    async def on_close_callback() -> None:
        nonlocal error_raised
        error_raised = True
        raise ValueError("Test error in on_close callback")

    # Create Mplex connection with on_close callback
    secured_conn = DummySecuredConn()
    mplex_conn = Mplex(secured_conn, DUMMY_PEER_ID, on_close=on_close_callback)

    # Start the connection to initialize it
    async with trio.open_nursery() as nursery:
        nursery.start_soon(mplex_conn.start)

        # Wait a bit for connection to start
        await trio.sleep(0.1)

        # Close the connection - should not raise even if callback has error
        await mplex_conn.close()

        # Wait a bit for cleanup to complete
        await trio.sleep(0.2)

        # Cancel the nursery to stop the start() task
        nursery.cancel_scope.cancel()

    # Verify callback was called (error was raised)
    assert error_raised, "on_close callback should have been called"
    # Connection should still be closed despite callback error
    assert mplex_conn.is_closed, (
        "Connection should be marked as closed even if callback errors"
    )


@pytest.mark.trio
async def test_mplex_on_close_callback_none():
    """Test that Mplex works correctly when on_close is None."""
    # Create Mplex connection without on_close callback
    secured_conn = DummySecuredConn()
    mplex_conn = Mplex(secured_conn, DUMMY_PEER_ID, on_close=None)

    # Start the connection to initialize it
    async with trio.open_nursery() as nursery:
        nursery.start_soon(mplex_conn.start)

        # Wait a bit for connection to start
        await trio.sleep(0.1)

        # Close the connection - should work fine without callback
        await mplex_conn.close()

        # Wait a bit for cleanup to complete
        await trio.sleep(0.2)

        # Cancel the nursery to stop the start() task
        nursery.cancel_scope.cancel()

    # Connection should be closed
    assert mplex_conn.is_closed, "Connection should be marked as closed"

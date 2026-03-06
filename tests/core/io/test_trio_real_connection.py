"""
Integration tests for ConnectionResetError handling with **real** TCP connections.

These tests complement the mock-based tests in test_trio_error_handling.py by
exercising the full error path over actual localhost TCP sockets, verifying that
the intended exceptions surface when a remote peer abruptly disconnects.

To force a true TCP RST (not a graceful FIN), the tests set SO_LINGER with a
zero timeout on the remote socket before closing it.  This causes the kernel to
send an RST segment instead of the normal FIN handshake, simulating a crash or
abrupt network failure.

Related: issue #376
"""

import logging
import socket
import struct

import pytest
import trio

from libp2p.io.exceptions import ConnectionClosedError
from libp2p.network.connection.exceptions import RawConnError
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.tcp.tcp import TCP
from libp2p.tools.constants import LISTEN_MADDR


logger = logging.getLogger(__name__)


def _force_reset(raw_conn: RawConnection) -> None:
    """
    Set SO_LINGER(on, timeout=0) on the underlying socket so that close()
    sends a TCP RST instead of a graceful FIN.

    This simulates an abrupt connection abort (e.g. remote process crash).
    """
    # Navigate: RawConnection -> TrioTCPStream -> trio.SocketStream -> socket
    trio_stream = raw_conn.stream            # TrioTCPStream
    socket_stream = trio_stream.stream       # trio.SocketStream
    sock = socket_stream.socket              # stdlib socket

    # struct.pack("ii", on, timeout) — on=1 enables linger, timeout=0 means RST
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))


@pytest.mark.trio
async def test_read_after_abrupt_reset_raises_error() -> None:
    """
    When the remote side sends a TCP RST (abrupt reset), a subsequent read()
    on the local side must raise ``RawConnError`` wrapping
    ``ConnectionClosedError``, NOT silently return b"".
    """
    async with trio.open_nursery() as nursery:
        local_conn: RawConnection | None = None
        remote_conn: RawConnection | None = None
        ready = trio.Event()

        async def on_accept(stream) -> None:
            nonlocal remote_conn
            remote_conn = RawConnection(stream, initiator=False)
            ready.set()
            await trio.sleep_forever()

        transport = TCP()
        listener = transport.create_listener(on_accept)
        await listener.listen(LISTEN_MADDR, nursery)
        local_conn = await transport.dial(listener.get_addrs()[0])
        await ready.wait()

        assert local_conn is not None and remote_conn is not None

        # Force the remote end to send RST on close (not graceful FIN)
        _force_reset(remote_conn)
        await remote_conn.close()

        # Give the OS a moment to deliver the RST
        await trio.sleep(0.05)

        # Reading from the local side should raise, not return b""
        with pytest.raises(RawConnError) as exc_info:
            await local_conn.read(1024)

        cause = exc_info.value.__cause__
        assert isinstance(cause, ConnectionClosedError)
        assert cause.transport == "tcp"
        logger.info(
            "read() raised RawConnError -> ConnectionClosedError on RST: %s", cause
        )

        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_write_after_abrupt_reset_raises_error() -> None:
    """
    When the remote side sends a TCP RST, a subsequent write() on the local
    side must raise ``RawConnError`` wrapping ``ConnectionClosedError``.
    """
    async with trio.open_nursery() as nursery:
        local_conn: RawConnection | None = None
        remote_conn: RawConnection | None = None
        ready = trio.Event()

        async def on_accept(stream) -> None:
            nonlocal remote_conn
            remote_conn = RawConnection(stream, initiator=False)
            ready.set()
            await trio.sleep_forever()

        transport = TCP()
        listener = transport.create_listener(on_accept)
        await listener.listen(LISTEN_MADDR, nursery)
        local_conn = await transport.dial(listener.get_addrs()[0])
        await ready.wait()

        assert local_conn is not None and remote_conn is not None

        # Force the remote end to send RST on close
        _force_reset(remote_conn)
        await remote_conn.close()

        # Give the OS a moment to deliver the RST
        await trio.sleep(0.05)

        # Write until the broken-pipe / reset is detected.
        # The first write may succeed (kernel buffers it), but subsequent
        # writes will fail because the peer sent RST.
        with pytest.raises(RawConnError) as exc_info:
            for _ in range(100):
                await local_conn.write(b"x" * 4096)
                await trio.sleep(0.01)

        cause = exc_info.value.__cause__
        assert isinstance(cause, ConnectionClosedError)
        assert cause.transport == "tcp"
        logger.info(
            "write() raised RawConnError -> ConnectionClosedError on RST: %s", cause
        )

        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_graceful_close_read_returns_eof() -> None:
    """
    A graceful close (normal FIN) should return b"" on read — NOT raise.
    This confirms the distinction between RST (error) and FIN (clean EOF).
    """
    async with trio.open_nursery() as nursery:
        local_conn: RawConnection | None = None
        remote_conn: RawConnection | None = None
        ready = trio.Event()

        async def on_accept(stream) -> None:
            nonlocal remote_conn
            remote_conn = RawConnection(stream, initiator=False)
            ready.set()
            await trio.sleep_forever()

        transport = TCP()
        listener = transport.create_listener(on_accept)
        await listener.listen(LISTEN_MADDR, nursery)
        local_conn = await transport.dial(listener.get_addrs()[0])
        await ready.wait()

        assert local_conn is not None and remote_conn is not None

        # Graceful close (no SO_LINGER hack) — sends FIN
        await remote_conn.close()
        await trio.sleep(0.05)

        # Should return empty bytes (EOF), NOT raise
        data = await local_conn.read(1024)
        assert data == b""
        logger.info("Graceful close correctly returned EOF (b'')")

        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_normal_data_transfer_works() -> None:
    """
    Sanity check: data transfer works normally over a real TCP connection
    before any reset occurs.
    """
    async with trio.open_nursery() as nursery:
        local_conn: RawConnection | None = None
        remote_conn: RawConnection | None = None
        ready = trio.Event()

        async def on_accept(stream) -> None:
            nonlocal remote_conn
            remote_conn = RawConnection(stream, initiator=False)
            ready.set()
            await trio.sleep_forever()

        transport = TCP()
        listener = transport.create_listener(on_accept)
        await listener.listen(LISTEN_MADDR, nursery)
        local_conn = await transport.dial(listener.get_addrs()[0])
        await ready.wait()

        assert local_conn is not None and remote_conn is not None

        # Normal round-trip
        await local_conn.write(b"hello from dialer")
        data = await remote_conn.read(1024)
        assert data == b"hello from dialer"

        await remote_conn.write(b"hello from listener")
        data = await local_conn.read(1024)
        assert data == b"hello from listener"

        logger.info("Normal data transfer works as expected")

        nursery.cancel_scope.cancel()

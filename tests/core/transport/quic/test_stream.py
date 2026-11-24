"""Unit tests for QUICStream behavior."""

from unittest.mock import Mock

import pytest
from multiaddr.multiaddr import Multiaddr
import trio
from trio.testing import wait_all_tasks_blocked

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.exceptions import QUICStreamResetError
from libp2p.transport.quic.stream import (
    QUICStream,
    StreamDirection,
    _QUICStreamEOF,
)


@pytest.fixture
def quic_connection() -> QUICConnection:
    mock_quic = Mock()
    mock_quic.next_event.return_value = None
    mock_quic.datagrams_to_send.return_value = []
    mock_quic.get_timer.return_value = None
    mock_quic.connect = Mock()
    mock_quic.close = Mock()
    mock_quic.send_stream_data = Mock()
    mock_quic.reset_stream = Mock()

    mock_transport = Mock()
    mock_transport._config = QUICTransportConfig()

    private_key = create_new_key_pair().private_key
    peer_id = ID.from_pubkey(private_key.get_public_key())

    return QUICConnection(
        quic_connection=mock_quic,
        remote_addr=("127.0.0.1", 4001),
        remote_peer_id=None,
        local_peer_id=peer_id,
        is_initiator=True,
        maddr=Multiaddr("/ip4/127.0.0.1/udp/4001/quic"),
        transport=mock_transport,
        resource_scope=None,
        security_manager=Mock(),
    )


@pytest.mark.trio
async def test_read_raises_reset_error_when_reset_during_wait(
    quic_connection: QUICConnection,
) -> None:
    """read() must detect peer reset while blocked on _receive_event."""
    stream = QUICStream(
        connection=quic_connection,
        stream_id=1,
        direction=StreamDirection.INBOUND,
        remote_addr=("127.0.0.1", 4001),
    )

    reset_error: QUICStreamResetError | None = None

    async def read_and_capture() -> None:
        nonlocal reset_error
        try:
            await stream.read()
        except QUICStreamResetError as exc:
            reset_error = exc

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_and_capture)
        await wait_all_tasks_blocked()
        await stream.handle_reset(error_code=1)

    assert reset_error is not None
    assert "reset" in str(reset_error).lower()


@pytest.mark.trio
async def test_read_eof_during_wait_does_not_reset_stream(
    quic_connection: QUICConnection,
) -> None:
    """
    A FIN arriving while read() is blocked is EOF, not a stream error.

    Regression: read() used to route _QUICStreamEOF through the generic error
    handler and reset the stream (error code 1), killing our own write side.
    The perf server hit this every time: it waits for the client's FIN and
    then has to write the reply on the same stream.
    """
    stream = QUICStream(
        connection=quic_connection,
        stream_id=1,
        direction=StreamDirection.INBOUND,
        remote_addr=("127.0.0.1", 4001),
    )

    caught: BaseException | None = None

    async def read_and_capture() -> None:
        nonlocal caught
        try:
            await stream.read()
        except BaseException as exc:  # noqa: BLE001 - we assert on the type below
            caught = exc

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_and_capture)
        await wait_all_tasks_blocked()
        await stream.handle_data_received(b"", end_stream=True)

    assert isinstance(caught, _QUICStreamEOF)
    assert not stream.is_reset()
    quic_connection._quic.reset_stream.assert_not_called()  # type: ignore[attr-defined]
    # Write side must still be usable after the peer's half-close.
    assert not stream._write_closed


@pytest.mark.trio
async def test_write_after_fin_raises_closed_without_reset(
    quic_connection: QUICConnection,
) -> None:
    """Map aioquic's after-FIN error to a closed error instead of a reset."""
    from aioquic.quic.exceptions import StreamStateError

    from libp2p.transport.quic.exceptions import QUICStreamClosedError

    stream = QUICStream(
        connection=quic_connection,
        stream_id=0,
        direction=StreamDirection.OUTBOUND,
        remote_addr=("127.0.0.1", 4001),
    )
    quic_connection._quic.send_stream_data.side_effect = StreamStateError(  # type: ignore[attr-defined]
        "Cannot send data after FIN"
    )

    with pytest.raises(QUICStreamClosedError):
        await stream.write(b"late")

    assert not stream.is_reset()
    quic_connection._quic.reset_stream.assert_not_called()  # type: ignore[attr-defined]

import logging
from unittest.mock import Mock

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import ConnectionType, ISecureConn
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.peer.id import ID
from libp2p.stream_muxer.mplex.datastructures import StreamID
from libp2p.stream_muxer.mplex.mplex import Mplex

DUMMY_PEER_ID = ID(b"dummy_peer_id")
MPLEX_LOGGER_NAME = "libp2p.stream_muxer.mplex.mplex"


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
        return Mock(spec=PrivateKey)

    def get_remote_peer(self) -> ID:
        return DUMMY_PEER_ID

    def get_remote_public_key(self) -> PublicKey:
        return Mock(spec=PublicKey)

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT


class _LogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def mplex_log_records():
    """
    Capture records from the mplex logger directly.

    pytest ``caplog`` is unreliable here because ``libp2p/utils/logging.py`` may
    set ``propagate=False`` on the ``libp2p`` hierarchy.
    """
    target = logging.getLogger(MPLEX_LOGGER_NAME)
    handler = _LogCollector()
    prev_level = target.level
    prev_disabled = target.disabled
    target.setLevel(logging.WARNING)
    target.disabled = False
    target.addHandler(handler)
    try:
        yield handler.records
    finally:
        target.removeHandler(handler)
        target.setLevel(prev_level)
        target.disabled = prev_disabled


@pytest.mark.trio
async def test_handle_incoming_unknown_flag_logs_warning(mplex_log_records):
    mplex = Mplex(DummySecuredConn(), DUMMY_PEER_ID)
    unknown_flag = 7
    channel_id = 42

    async def fake_read_message() -> tuple[int, int, bytes]:
        return channel_id, unknown_flag, b""

    mplex.read_message = fake_read_message  # type: ignore[method-assign]

    await mplex._handle_incoming_message()

    assert any(
        f"Received message with unknown flag: {unknown_flag}" in record.getMessage()
        for record in mplex_log_records
    )


@pytest.mark.trio
async def test_handle_message_nonexistent_stream_logs_warning(mplex_log_records):
    mplex = Mplex(DummySecuredConn(), DUMMY_PEER_ID)
    stream_id = StreamID(channel_id=99, is_initiator=True)

    await mplex._handle_message(stream_id, b"payload")

    assert any(
        f"Received message for non-existent stream: {stream_id}" in record.getMessage()
        for record in mplex_log_records
    )


@pytest.mark.trio
async def test_handle_message_after_remote_close_logs_warning(mplex_log_records):
    mplex = Mplex(DummySecuredConn(), DUMMY_PEER_ID)
    stream_id = StreamID(channel_id=1, is_initiator=True)
    stream = await mplex._initialize_stream(stream_id, "1")
    stream.event_remote_closed.set()
    payload = b"late-data"

    await mplex._handle_message(stream_id, payload)

    assert any(
        "Received data from remote after stream was closed by them. "
        f"(len = {len(payload)})" in record.getMessage()
        for record in mplex_log_records
    )
    # Message must not be delivered after remote close.
    with pytest.raises(trio.WouldBlock):
        stream.incoming_data_channel.receive_nowait()

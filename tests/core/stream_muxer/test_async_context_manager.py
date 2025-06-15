import pytest
import trio

from libp2p.abc import ISecureConn
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.peer.id import ID
from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamError,
)
from libp2p.stream_muxer.mplex.datastructures import (
    StreamID,
)
from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.stream_muxer.mplex.mplex_stream import (
    MplexStream,
)
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
    YamuxStream,
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
        return PrivateKey()  # Dummy key

    def get_remote_peer(self) -> ID:
        return ID(b"remote")

    def get_remote_public_key(self) -> PublicKey:
        return PublicKey()  # Dummy key


class MockMuxedConn:
    def __init__(self):
        self.streams = {}
        self.streams_lock = trio.Lock()
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()
        self.secured_conn = DummySecuredConn()  # For YamuxStream

    async def send_message(self, flag, data, stream_id):
        pass

    def get_remote_address(self):
        return None


class MockMplexMuxedConn:
    def __init__(self):
        self.streams_lock = trio.Lock()
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()

    async def send_message(self, flag, data, stream_id):
        pass

    def get_remote_address(self):
        return None


class MockYamuxMuxedConn:
    def __init__(self):
        self.secured_conn = DummySecuredConn()
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()

    async def send_message(self, flag, data, stream_id):
        pass

    def get_remote_address(self):
        return None


@pytest.mark.trio
async def test_mplex_stream_async_context_manager():
    muxed_conn = Mplex(DummySecuredConn(), DUMMY_PEER_ID)
    stream_id = StreamID(1, True)  # Use real StreamID
    stream = MplexStream(
        name="test_stream",
        stream_id=stream_id,
        muxed_conn=muxed_conn,
        incoming_data_channel=trio.open_memory_channel(8)[1],
    )
    async with stream as s:
        assert s is stream
        assert not stream.event_local_closed.is_set()
        assert not stream.event_remote_closed.is_set()
        assert not stream.event_reset.is_set()
    assert stream.event_local_closed.is_set()


@pytest.mark.trio
async def test_yamux_stream_async_context_manager():
    muxed_conn = Yamux(DummySecuredConn(), DUMMY_PEER_ID)
    stream = YamuxStream(stream_id=1, conn=muxed_conn, is_initiator=True)
    async with stream as s:
        assert s is stream
        assert not stream.closed
        assert not stream.send_closed
        assert not stream.recv_closed
    assert stream.send_closed


@pytest.mark.trio
async def test_mplex_stream_async_context_manager_with_error():
    muxed_conn = Mplex(DummySecuredConn(), DUMMY_PEER_ID)
    stream_id = StreamID(1, True)
    stream = MplexStream(
        name="test_stream",
        stream_id=stream_id,
        muxed_conn=muxed_conn,
        incoming_data_channel=trio.open_memory_channel(8)[1],
    )
    with pytest.raises(ValueError):
        async with stream as s:
            assert s is stream
            assert not stream.event_local_closed.is_set()
            assert not stream.event_remote_closed.is_set()
            assert not stream.event_reset.is_set()
            raise ValueError("Test error")
    assert stream.event_local_closed.is_set()


@pytest.mark.trio
async def test_yamux_stream_async_context_manager_with_error():
    muxed_conn = Yamux(DummySecuredConn(), DUMMY_PEER_ID)
    stream = YamuxStream(stream_id=1, conn=muxed_conn, is_initiator=True)
    with pytest.raises(ValueError):
        async with stream as s:
            assert s is stream
            assert not stream.closed
            assert not stream.send_closed
            assert not stream.recv_closed
            raise ValueError("Test error")
    assert stream.send_closed


@pytest.mark.trio
async def test_mplex_stream_async_context_manager_write_after_close():
    muxed_conn = Mplex(DummySecuredConn(), DUMMY_PEER_ID)
    stream_id = StreamID(1, True)
    stream = MplexStream(
        name="test_stream",
        stream_id=stream_id,
        muxed_conn=muxed_conn,
        incoming_data_channel=trio.open_memory_channel(8)[1],
    )
    async with stream as s:
        assert s is stream
    with pytest.raises(MuxedStreamClosed):
        await stream.write(b"test data")


@pytest.mark.trio
async def test_yamux_stream_async_context_manager_write_after_close():
    muxed_conn = Yamux(DummySecuredConn(), DUMMY_PEER_ID)
    stream = YamuxStream(stream_id=1, conn=muxed_conn, is_initiator=True)
    async with stream as s:
        assert s is stream
    with pytest.raises(MuxedStreamError):
        await stream.write(b"test data")

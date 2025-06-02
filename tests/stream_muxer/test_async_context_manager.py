import pytest
import trio

from libp2p.stream_muxer.exceptions import (
    MuxedStreamClosed,
    MuxedStreamError,
)
from libp2p.stream_muxer.mplex.datastructures import (
    StreamID,
)
from libp2p.stream_muxer.mplex.mplex_stream import (
    MplexStream,
)
from libp2p.stream_muxer.yamux.yamux import (
    YamuxStream,
)


class DummySecuredConn:
    async def write(self, data):
        pass


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


@pytest.mark.trio
async def test_mplex_stream_async_context_manager():
    muxed_conn = MockMuxedConn()
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
    muxed_conn = MockMuxedConn()
    stream = YamuxStream(stream_id=1, conn=muxed_conn, is_initiator=True)
    async with stream as s:
        assert s is stream
        assert not stream.closed
        assert not stream.send_closed
        assert not stream.recv_closed
    assert stream.send_closed


@pytest.mark.trio
async def test_mplex_stream_async_context_manager_with_error():
    muxed_conn = MockMuxedConn()
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
    muxed_conn = MockMuxedConn()
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
    muxed_conn = MockMuxedConn()
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
    muxed_conn = MockMuxedConn()
    stream = YamuxStream(stream_id=1, conn=muxed_conn, is_initiator=True)
    async with stream as s:
        assert s is stream
    with pytest.raises(MuxedStreamError):
        await stream.write(b"test data")

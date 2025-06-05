import pytest
import trio

from libp2p.stream_muxer.mplex.datastructures import (
    StreamID,
)
from libp2p.stream_muxer.mplex.mplex_stream import (
    MplexStream,
)


class DummyMuxedConn:
    async def send_message(self, flag, data, stream_id):
        await trio.sleep(0.01)


@pytest.mark.trio
async def test_concurrent_writes_are_serialized():
    stream_id = StreamID(1, True)
    DummyMuxedConn()
    send_log = []

    class LoggingMuxedConn(DummyMuxedConn):
        async def send_message(self, flag, data, stream_id):
            send_log.append(data)
            await trio.sleep(0.01)

    memory_send, memory_recv = trio.open_memory_channel(8)
    stream = MplexStream(
        name="test",
        stream_id=stream_id,
        muxed_conn=LoggingMuxedConn(),
        incoming_data_channel=memory_recv,
    )

    async def writer(data):
        await stream.write(data)

    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(writer, f"msg-{i}".encode())
    # Order doesn't matter due to concurrent execution
    assert sorted(send_log) == sorted([f"msg-{i}".encode() for i in range(5)])


@pytest.mark.trio
async def test_concurrent_reads_are_serialized():
    stream_id = StreamID(2, True)
    muxed_conn = DummyMuxedConn()
    memory_send, memory_recv = trio.open_memory_channel(8)
    results = []
    stream = MplexStream(
        name="test",
        stream_id=stream_id,
        muxed_conn=muxed_conn,
        incoming_data_channel=memory_recv,
    )
    for i in range(5):
        await memory_send.send(f"data-{i}".encode())
    await memory_send.aclose()

    async def reader():
        data = await stream.read(6)
        results.append(data)

    async with trio.open_nursery() as nursery:
        for _ in range(5):
            nursery.start_soon(reader)
    assert sorted(results) == [f"data-{i}".encode() for i in range(5)]

import pytest
import trio

from libp2p.stream_muxer.yamux.yamux import (
    YamuxStream,
)


class DummySecuredConn:
    async def write(self, data):
        await trio.sleep(0.01)


class DummyYamux:
    def __init__(self):
        self.secured_conn = DummySecuredConn()
        self.stream_buffers = {}
        self.stream_events = {}
        self.event_shutting_down = trio.Event()
        self.streams_lock = trio.Lock()

    async def read_stream(self, stream_id, n=-1):
        # Simulate reading n bytes from the buffer
        buf = self.stream_buffers.get(stream_id, bytearray())
        if n == -1 or n >= len(buf):
            data = bytes(buf)
            buf.clear()
        else:
            data = bytes(buf[:n])
            del buf[:n]
        return data


@pytest.mark.trio
async def test_concurrent_writes_are_serialized():
    yamux = DummyYamux()
    send_log = []

    class LoggingSecuredConn(DummySecuredConn):
        async def write(self, data):
            send_log.append(data)
            await trio.sleep(0.01)

    yamux.secured_conn = LoggingSecuredConn()
    stream = YamuxStream(stream_id=1, conn=yamux, is_initiator=True)

    async def writer(data):
        await stream.write(data)

    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(writer, f"msg-{i}".encode())

    # All messages should be present, order may vary
    assert len(send_log) == 5
    payloads = [msg[12:] for msg in send_log]  # Assuming 12-byte header
    assert sorted(payloads) == [f"msg-{i}".encode() for i in range(5)]


@pytest.mark.trio
async def test_concurrent_reads_are_serialized():
    yamux = DummyYamux()
    stream_id = 2
    yamux.stream_buffers[stream_id] = bytearray()
    yamux.stream_events[stream_id] = trio.Event()
    stream = YamuxStream(stream_id=stream_id, conn=yamux, is_initiator=True)

    # Preload the buffer
    for i in range(5):
        yamux.stream_buffers[stream_id].extend(f"data-{i}".encode())

    results = []

    async def reader():
        data = await stream.read(6)
        results.append(data)

    async with trio.open_nursery() as nursery:
        for _ in range(5):
            nursery.start_soon(reader)

    assert sorted(results) == [f"data-{i}".encode() for i in range(5)]

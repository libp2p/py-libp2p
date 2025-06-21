import pytest
import trio

from libp2p.abc import IMuxedStream, ISecureConn
from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.peer.id import ID
from libp2p.stream_muxer.mplex.constants import (
    HeaderTags,
)
from libp2p.stream_muxer.mplex.datastructures import (
    StreamID,
)
from libp2p.stream_muxer.mplex.mplex import (
    Mplex,
)
from libp2p.stream_muxer.mplex.mplex_stream import (
    MplexStream,
)


class DummySecureConn(ISecureConn):
    """A minimal implementation of ISecureConn for testing."""

    async def write(self, data: bytes) -> None:
        pass

    async def read(self, n: int | None = -1) -> bytes:
        return b""

    async def close(self) -> None:
        pass

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_local_peer(self) -> ID:
        return ID(b"local")

    def get_local_private_key(self) -> PrivateKey:
        return PrivateKey()  # Dummy key for testing

    def get_remote_peer(self) -> ID:
        return ID(b"remote")

    def get_remote_public_key(self) -> PublicKey:
        return PublicKey()  # Dummy key for testing


class DummyMuxedConn(Mplex):
    """A minimal mock of Mplex for testing read/write locks."""

    def __init__(self) -> None:
        self.secured_conn = DummySecureConn()
        self.peer_id = ID(b"dummy")
        self.streams = {}
        self.streams_lock = trio.Lock()
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()
        self.stream_backlog_limit = 256
        self.stream_backlog_semaphore = trio.Semaphore(256)
        # Use IMuxedStream for type consistency with Mplex
        channels = trio.open_memory_channel[IMuxedStream](0)
        self.new_stream_send_channel, self.new_stream_receive_channel = channels

    async def send_message(
        self, flag: HeaderTags, data: bytes | None, stream_id: StreamID
    ) -> int:
        await trio.sleep(0.01)
        return 0


@pytest.mark.trio
async def test_concurrent_writes_are_serialized():
    stream_id = StreamID(1, True)
    send_log = []

    class LoggingMuxedConn(DummyMuxedConn):
        async def send_message(
            self, flag: HeaderTags, data: bytes | None, stream_id: StreamID
        ) -> int:
            send_log.append(data)
            await trio.sleep(0.01)
            return 0

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

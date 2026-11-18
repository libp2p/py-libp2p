"""Regression checks for ownership retained after one-shot network operations."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.packet_builder import QuicDeliveryState
import trio

from libp2p.abc import IHost, ISecureConn
from libp2p.host.ping import PingService
from libp2p.kad_dht.routing_table import KBucket
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.stream.net_stream import NetStream
from libp2p.peer.id import ID
from libp2p.stream_muxer.yamux.yamux import Yamux, YamuxStream
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.stream import QUICStream, StreamDirection


@pytest.mark.trio
async def test_dht_probes_release_listeners_and_streams():
    notifees = []
    network = SimpleNamespace(
        register_notifee=notifees.append, remove_notifee=notifees.remove
    )
    streams = []

    class EchoStream:
        is_closed = False

        def __init__(self):
            self.payload = b""

        async def write(self, data):
            self.payload = data

        async def read(self, n):
            return self.payload

        async def reset(self):
            await trio.lowlevel.checkpoint()
            self.is_closed = True

    async def new_stream(*args):
        stream = EchoStream()
        streams.append(stream)
        return stream

    host: Any = SimpleNamespace(
        get_network=lambda: network,
        new_stream=new_stream,
        get_event_bus=lambda: SimpleNamespace(emit=lambda e: None),
    )
    bucket = KBucket(host)
    peer_id = ID(b"same-peer")
    for _ in range(100):
        assert await bucket._ping_peer(peer_id)
        assert not notifees
    assert all(stream.is_closed for stream in streams)

    async def fail(*args):
        raise OSError("dial failed")

    host.new_stream = fail
    assert not await bucket._ping_peer(peer_id)
    assert not notifees

    async def block(*args):
        await trio.sleep_forever()

    host.new_stream = block
    with trio.move_on_after(0.01) as scope:
        await bucket._ping_peer(peer_id)
    assert scope.cancelled_caught
    assert not notifees


@pytest.mark.trio
async def test_outer_ping_deadline_resets_stream_and_preserves_cancellation():
    class Stream:
        is_closed = False
        reset_calls = 0

        async def write(self, data):
            await trio.sleep_forever()

        async def reset(self):
            # Cleanup must reach checkpoints even under outer cancellation.
            await trio.lowlevel.checkpoint()
            self.reset_calls += 1

    stream = Stream()

    async def new_stream(*args):
        return stream

    service = PingService(cast(IHost, SimpleNamespace(new_stream=new_stream)))
    with pytest.raises(trio.TooSlowError):
        with trio.fail_after(0.01):
            await service.ping(ID(b"peer"))
    assert stream.reset_calls == 1
    assert not service._outbound_streams


@pytest.mark.trio
async def test_quic_reset_requests_receive_termination_and_wakes_readers():
    quic = QuicConnection(configuration=QuicConfiguration(is_client=True))
    quic.send_stream_data(0, b"probe")
    removed = []

    async def transmit():
        pass

    parent = SimpleNamespace(
        _quic=quic,
        _transmit=transmit,
        _remove_stream=removed.append,
        _transport=SimpleNamespace(_config=QUICTransportConfig()),
        remote_peer_id=lambda: "peer",
        stream_send_buffer_size=lambda sid: 0,
        _signal_activity=lambda: None,
    )
    stream = QUICStream(
        cast(QUICConnection, parent), 0, StreamDirection.OUTBOUND, ("127.0.0.1", 1)
    )
    await stream.reset(error_code=7)
    transport_stream = quic._streams[0]
    assert transport_stream.receiver.stop_pending
    transport_stream.sender.on_reset_delivery(QuicDeliveryState.ACKED)
    transport_stream.receiver.handle_reset(final_size=0)
    assert transport_stream.is_finished
    assert removed == [0]
    assert stream._receive_event.is_set()


@pytest.mark.trio
async def test_quic_close_read_requests_stop_without_resetting_write():
    quic = QuicConnection(configuration=QuicConfiguration(is_client=True))
    quic.send_stream_data(0, b"probe")

    async def transmit():
        pass

    parent = SimpleNamespace(
        _quic=quic,
        _transmit=transmit,
        _transport=SimpleNamespace(_config=QUICTransportConfig()),
        remote_peer_id=lambda: "peer",
        stream_send_buffer_size=lambda sid: 0,
        _signal_activity=lambda: None,
    )
    stream = QUICStream(
        cast(QUICConnection, parent), 0, StreamDirection.OUTBOUND, ("127.0.0.1", 1)
    )
    await stream.close_read()
    assert quic._streams[0].receiver.stop_pending
    assert not quic._streams[0].sender.reset_pending
    await stream.write(b"still writable")


@pytest.mark.trio
async def test_yamux_full_close_is_bounded_but_write_half_close_is_preserved():
    async def write(data):
        pass

    async def notify(stream):
        pass

    yamux = Yamux(
        cast(ISecureConn, SimpleNamespace(is_initiator=True, write=write)), ID(b"peer")
    )
    conn = cast(
        SwarmConn,
        SimpleNamespace(
            muxed_conn=yamux,
            remove_stream=lambda stream: None,
            swarm=SimpleNamespace(notify_closed_stream=notify),
        ),
    )
    full = NetStream(await yamux.open_stream(), conn, None)
    half = NetStream(await yamux.open_stream(), conn, None)
    await full.close()
    await half.close_write()
    abandoned = cast(YamuxStream, full.muxed_stream)
    half_stream = cast(YamuxStream, half.muxed_stream)
    assert half_stream.send_closed
    assert half_stream._read_abandoned_at is None
    closed_at = abandoned._read_abandoned_at
    assert closed_at is not None
    assert await yamux._reset_abandoned_streams(now=closed_at) == 0
    assert await yamux._reset_abandoned_streams(now=closed_at + 1000) == 1
    assert abandoned.stream_id not in yamux.streams
    assert half_stream.stream_id in yamux.streams
    assert not half_stream.recv_closed


class _EchoPingStream:
    """Minimal INetStream stand-in that echoes a 32-byte ping."""

    is_closed = False

    def __init__(self):
        self._pending = b""

    async def write(self, data):
        await trio.lowlevel.checkpoint()
        self._pending = data

    async def read(self, n):
        await trio.lowlevel.checkpoint()
        data, self._pending = self._pending[:n], self._pending[n:]
        return data

    async def close(self):
        await trio.lowlevel.checkpoint()
        self.is_closed = True

    async def reset(self):
        await trio.lowlevel.checkpoint()
        self.is_closed = True


def _ping_host(new_stream):
    return cast(
        IHost,
        SimpleNamespace(
            new_stream=new_stream,
            get_event_bus=lambda: SimpleNamespace(emit=lambda event: None),
        ),
    )


@pytest.mark.trio
async def test_concurrent_pings_share_one_stream_and_aclose_releases_it():
    """
    Overlapping first pings must not each open (and orphan) a stream.

    The cache lookup and stream creation were not serialized, so N callers
    could all cache-miss, open N streams and leave only the last one reachable
    through the service registry.
    """
    opened: list[_EchoPingStream] = []

    async def new_stream(*args):
        await trio.lowlevel.checkpoint()
        stream = _EchoPingStream()
        opened.append(stream)
        return stream

    service = PingService(_ping_host(new_stream))
    peer = ID(b"peer")

    async with trio.open_nursery() as nursery:
        for _ in range(25):
            nursery.start_soon(service.ping, peer)

    assert len(opened) == 1
    assert len(service._outbound_streams) == 1
    # The per-peer lock registry must not retain idle peers.
    assert service._peer_locks == {}

    await service.aclose()
    assert opened[0].is_closed
    assert service._outbound_streams == {}


@pytest.mark.trio
async def test_aclose_during_stream_open_does_not_adopt_new_stream():
    """A ping that resumes after aclose() must release its stream, not keep it."""
    gate = trio.Event()
    opened = trio.Event()
    created: list[_EchoPingStream] = []
    errors: list[BaseException] = []

    async def new_stream(*args):
        stream = _EchoPingStream()
        created.append(stream)
        opened.set()
        await gate.wait()
        return stream

    service = PingService(_ping_host(new_stream))

    async def run_ping():
        try:
            await service.ping(ID(b"peer"))
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion
            errors.append(error)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_ping)
        await opened.wait()
        await service.aclose()
        gate.set()

    assert errors and isinstance(errors[0], RuntimeError)
    assert created[0].is_closed
    assert service._outbound_streams == {}


@pytest.mark.trio
async def test_cancelled_inbound_ping_handler_resets_stream():
    """External cancellation must not leave the muxed stream owned."""
    stream = _EchoPingStream()
    stream.muxed_conn = SimpleNamespace(peer_id=ID(b"peer"))

    async def read_forever(n):
        await trio.sleep_forever()

    stream.read = read_forever

    service = PingService(_ping_host(lambda *args: None))
    with trio.move_on_after(0.02) as scope:
        await service.handle_ping(stream)

    assert scope.cancelled_caught
    assert stream.is_closed
    assert service._inbound_streams == {}


@pytest.mark.trio
async def test_inbound_handler_return_releases_muxed_stream():
    """
    An inbound handler that returns without closing must not leak the stream.

    The connection wrapper dropped the NetStream but left the muxed stream
    registered, and Yamux only reclaims fully-closed entries, so every
    abandoned inbound handler pinned a stream, buffer and event object for the
    lifetime of the connection.
    """

    async def write(data):
        return None

    mux = Yamux(
        SimpleNamespace(is_initiator=True, write=write), ID(b"peer"), is_initiator=False
    )
    notified: list[Any] = []

    async def noop(*args):
        return None

    async def notify_closed(stream):
        stream._resource_released = True
        notified.append(stream)

    conn = SwarmConn(
        mux,
        SimpleNamespace(notify_opened_stream=noop, notify_closed_stream=notify_closed),
    )
    conn.event_started.set()

    async def handler(stream):
        return None

    conn.swarm.common_stream_handler = handler

    for stream_id in range(2, 22, 2):
        stream = YamuxStream(stream_id, mux, False)
        async with mux.streams_lock:
            mux.streams[stream_id] = stream
            mux.stream_buffers[stream_id] = bytearray()
            mux.stream_events[stream_id] = trio.Event()
            # Peer already sent its FIN; nothing else can arrive.
            stream.recv_closed = True
        await conn._handle_muxed_stream(stream)

    assert mux.streams == {}
    assert mux.stream_buffers == {}
    assert mux.stream_events == {}
    assert len(notified) == 10
    assert conn.streams == set()


@pytest.mark.trio
async def test_cancelled_open_stream_releases_bookkeeping_and_backlog_slot():
    """
    Cancelling open_stream() mid-SYN must not strand the stream registration.

    The stream was registered, then the caller's deadline fired inside the SYN
    write: the entry, its buffer, its event and one backlog slot stayed charged
    for the connection's lifetime, and no caller could ever close it.
    """

    async def write(data):
        await trio.sleep_forever()

    mux = Yamux(SimpleNamespace(is_initiator=True, write=write), ID(b"peer"))

    for _ in range(10):
        with trio.move_on_after(0.02) as scope:
            await mux.open_stream()
        assert scope.cancelled_caught

    assert mux.streams == {}
    assert mux.stream_buffers == {}
    assert mux.stream_events == {}
    assert mux.stream_backlog_semaphore.value == mux.stream_backlog_limit

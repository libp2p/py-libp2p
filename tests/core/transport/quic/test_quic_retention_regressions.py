"""
Regression tests for the QUIC ownership findings fixed in this round.

Each test mirrors one probe from ``investigation/quic_audit_2026-11-18.py``
and asserts the bounded/cleaned-up end state instead of the raw counters.
"""

from __future__ import annotations

import gc
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
import weakref

import pytest
from aioquic.buffer import Buffer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import StopSendingReceived, StreamDataReceived
from aioquic.quic.packet import QuicFrameType
from aioquic.quic.packet_builder import QuicDeliveryState
from multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.exceptions import QUICDialError, QUICListenError
from libp2p.transport.quic.transport import QUICTransport


async def _ignore(*args):
    pass


def make_transport() -> QUICTransport:
    return QUICTransport(create_new_key_pair().private_key)


def make_conn(transport=None) -> tuple[QuicConnection, QUICConnection]:
    raw = QuicConnection(configuration=QuicConfiguration(is_client=True))
    transport = transport or SimpleNamespace(_config=QUICTransportConfig())
    conn = QUICConnection(
        raw,
        ("127.0.0.1", 1),
        ID(b"remote"),
        ID(b"local"),
        True,
        Multiaddr("/ip4/127.0.0.1/udp/1/quic-v1"),
        transport,
    )
    conn._started = True
    return raw, conn


class _FrameBuilder:
    def start_frame(self, *args, **kwargs):
        return Buffer(capacity=256)


@pytest.mark.trio
async def test_retired_connection_id_leaves_listener_registry():
    transport = make_transport()
    listener = transport.create_listener(_ignore)
    raw, conn = make_conn(transport)
    conn._listener = listener
    conn._listener_connection_id = raw.host_cid
    await listener._registry.register_connection(raw.host_cid, conn, conn._remote_addr)
    raw._replenish_connection_ids()
    context = SimpleNamespace(host_cid=raw.host_cid)
    builder = _FrameBuilder()

    for _ in range(50):
        cid = next(c for c in raw._host_cids if c.sequence_number > 0)
        raw._write_new_connection_id_frame(builder, cid)
        while (event := raw.next_event()) is not None:
            await conn._handle_quic_event(event)
        frame = Buffer(capacity=16)
        frame.push_uint_var(cid.sequence_number)
        raw._handle_retire_connection_id_frame(
            context, QuicFrameType.RETIRE_CONNECTION_ID, Buffer(data=frame.data)
        )
        while (event := raw.next_event()) is not None:
            await conn._handle_quic_event(event)

    registry = listener._registry
    assert len(registry._connections) == 1
    assert len(registry._connection_sequences.get(conn, {})) == 1
    assert len(registry._connection_id_to_addr) == 1

    await conn.close()
    await listener.close()


@pytest.mark.trio
async def test_retransmitted_connection_id_does_not_add_sequences():
    transport = make_transport()
    listener = transport.create_listener(_ignore)
    raw, conn = make_conn(transport)
    conn._listener = listener
    conn._listener_connection_id = raw.host_cid
    await listener._registry.register_connection(raw.host_cid, conn, conn._remote_addr)
    raw._replenish_connection_ids()
    builder = _FrameBuilder()

    for _ in range(50):
        cid = next(c for c in raw._host_cids if c.sequence_number > 0)
        raw._write_new_connection_id_frame(builder, cid)
        while (event := raw.next_event()) is not None:
            await conn._handle_quic_event(event)
        raw._on_new_connection_id_delivery(QuicDeliveryState.LOST, cid)

    registry = listener._registry
    assert len(registry._connections) == len(raw._host_cids)
    assert len(registry._connection_sequences.get(conn, {})) == len(raw._host_cids)

    await conn.close()
    await listener.close()


@pytest.mark.trio
async def test_unauthenticated_fallback_packets_do_not_add_aliases():
    transport = make_transport()
    listener = transport.create_listener(_ignore)
    raw, conn = make_conn(transport)
    raw.connect(conn._remote_addr, now=time.time())
    await listener._registry.register_connection(raw.host_cid, conn, conn._remote_addr)

    for i in range(200):
        cid = (i + 12345).to_bytes(8, "big")
        await listener._process_packet(b"\x40" + cid + bytes(32), conn._remote_addr)

    registry = listener._registry
    assert listener._stats["fallback_routing_used"] > 0
    assert len(registry._connections) == 1
    assert len(registry._connection_id_to_addr) == 1

    await registry.unregister_connection_object(conn)
    await listener.close()


@pytest.mark.trio
async def test_closed_streams_do_not_grow_accept_backlog_unbounded():
    _raw, conn = make_conn()
    # Keep the configured limits low so the test stays under aioquic's own
    # peer-initiated stream limit (100 by default).
    conn.MAX_QUEUED_INBOUND_STREAMS = 20
    conn.MAX_QUEUED_INBOUND_BYTES = 512 * 1024
    async with trio.open_nursery() as nursery:
        conn._nursery = nursery
        for i in range(60):
            stream_id = 1 + 4 * i
            _raw._get_or_create_stream(0x08, stream_id)
            await conn._handle_quic_event(
                StreamDataReceived(
                    data=bytes(65536), end_stream=True, stream_id=stream_id
                )
            )
            await conn._handle_quic_event(
                StopSendingReceived(error_code=0, stream_id=stream_id)
            )
        await trio.sleep(0)
        assert len(conn._streams) == 0

        queued = conn._stream_accept_queue
        assert len(queued) <= conn.MAX_QUEUED_INBOUND_STREAMS
        assert (
            sum(len(stream._receive_buffer) for stream in queued)
            <= conn.MAX_QUEUED_INBOUND_BYTES
        )
        conn._nursery = None

    conn._stream_accept_queue.clear()
    gc.collect()


@pytest.mark.trio
@pytest.mark.parametrize("batched", [False, True])
async def test_accept_backlog_budget_applies_to_later_data(batched):
    raw, conn = make_conn()

    async def deliver(stream_id, data, end_stream=False):
        event = StreamDataReceived(
            data=data, end_stream=end_stream, stream_id=stream_id
        )
        if batched:
            await conn._handle_stream_data_batch([event])
        else:
            await conn._handle_stream_data(event)

    async with trio.open_nursery() as nursery:
        conn._nursery = nursery
        # All streams enter the queue before their large payload arrives.
        for i in range(32):
            stream_id = 1 + 4 * i
            raw._get_or_create_stream(0x08, stream_id)
            await deliver(stream_id, b"x")

        for i in range(32):
            stream_id = 1 + 4 * i
            await deliver(stream_id, bytes(1024 * 1024 - 1), True)
            await conn._handle_quic_event(
                StopSendingReceived(error_code=0, stream_id=stream_id)
            )
            assert (
                sum(len(s._receive_buffer) for s in conn._stream_accept_queue)
                <= conn.MAX_QUEUED_INBOUND_BYTES
            )

        assert len(conn._stream_accept_queue) == 4
        assert conn._stats["inbound_streams_dropped"] == 28
        # Surviving FIN-closed streams must retain their unread payload.
        for i in range(28, 32):
            stream = await conn.accept_stream()
            assert int(stream.stream_id) == 1 + 4 * i
            assert await stream.read(1024 * 1024) == b"x" + bytes(1024 * 1024 - 1)
        await conn.close()
        conn._nursery = None


@pytest.mark.trio
@pytest.mark.parametrize("batched", [False, True])
async def test_accept_backlog_budget_excludes_accepted_streams(batched):
    raw, conn = make_conn()
    conn.MAX_QUEUED_INBOUND_BYTES = 64
    async with trio.open_nursery() as nursery:
        conn._nursery = nursery
        raw._get_or_create_stream(0x08, 1)
        await conn._handle_stream_data(
            StreamDataReceived(data=b"x", end_stream=False, stream_id=1)
        )
        accepted = await conn.accept_stream()
        event = StreamDataReceived(data=bytes(128), end_stream=True, stream_id=1)
        if batched:
            await conn._handle_stream_data_batch([event])
        else:
            await conn._handle_stream_data(event)
        assert not accepted.is_reset()
        assert await accepted.read(129) == b"x" + bytes(128)
        await conn.close()
        conn._nursery = None


@pytest.mark.trio
@pytest.mark.parametrize("batched", [False, True])
@pytest.mark.parametrize("cancel_delivery", [False, True])
async def test_accept_backlog_eviction_releases_live_stream(batched, cancel_delivery):
    raw, conn = make_conn()
    conn.MAX_QUEUED_INBOUND_BYTES = 64
    async with trio.open_nursery() as nursery:
        conn._nursery = nursery
        raw._get_or_create_stream(0x08, 1)
        stream = await conn._create_inbound_stream(1)
        resource_scope = Mock()
        stream._resource_scope = resource_scope
        stream._memory_reserved = 17
        callback = Mock()

        async def on_close():
            # Eviction must not hold the connection lock across callbacks.
            async with conn._stream_lock:
                callback()

        await stream.set_close_callback(on_close)
        original_receive = stream.handle_data_received
        with trio.CancelScope() as cancel_scope:

            async def receive_then_cancel(data, end_stream):
                await original_receive(data, end_stream)
                cancel_scope.cancel()
                await trio.lowlevel.checkpoint()

            if cancel_delivery:
                stream.handle_data_received = receive_then_cancel
            event = StreamDataReceived(data=bytes(128), end_stream=False, stream_id=1)
            if batched:
                # The second event must not refill the evicted wrapper, even
                # though the batch still holds a reference to it.
                await conn._handle_stream_data_batch([event, event])
            else:
                await conn._handle_stream_data(event)

        assert cancel_scope.cancelled_caught == cancel_delivery
        assert not conn._stream_accept_queue
        assert not conn._streams
        assert not conn._stream_cache
        assert stream.is_reset()
        assert not stream._receive_buffer
        assert stream._memory_reserved == 0
        resource_scope.release_memory.assert_called_once_with(17)
        resource_scope.close.assert_called_once_with()
        callback.assert_called_once_with()
        assert conn._stats["inbound_streams_dropped"] == 1
        await conn.close()
        conn._nursery = None


@pytest.mark.trio
async def test_cancelled_stop_sending_still_closes_stream():
    raw, conn = make_conn()
    callbacks: list[bool] = []

    async def callback():
        callbacks.append(True)

    ordinary_transmit = conn._transmit
    async with trio.open_nursery() as nursery:
        conn._nursery = nursery
        for _ in range(10):
            stream = await conn.open_stream()
            raw.send_stream_data(stream._stream_id, b"request")
            await stream.handle_data_received(bytes(65536), False)
            await stream.set_close_callback(callback)
            with trio.CancelScope() as scope:

                async def cancel_during_send():
                    scope.cancel()
                    await trio.lowlevel.checkpoint()

                conn._transmit = cancel_during_send
                await stream.handle_stop_sending(0)
            assert scope.cancelled_caught
            conn._transmit = ordinary_transmit

        assert len(conn._streams) == 0
        assert len(callbacks) == 10
        conn._nursery = None


@pytest.mark.trio
async def test_cancelled_promotion_rolls_back_registry():
    transport = make_transport()
    listener = transport.create_listener(_ignore)

    for i in range(20):
        raw, conn = make_conn(transport)
        conn._is_initiator = False
        addr = ("127.0.0.1", 30000 + i)
        cid = i.to_bytes(8, "big")
        await listener._registry.register_pending(cid, raw, addr)
        listener._pending_cid_by_quic_id[id(raw)] = cid
        listener._conn_by_quic_id[id(raw)] = conn

        with trio.CancelScope() as scope:

            async def cancelled_cert():
                scope.cancel()
                await trio.lowlevel.checkpoint()

            conn.get_peer_certificate = cancelled_cert
            await listener._promote_pending_connection(raw, addr, cid)
        assert scope.cancelled_caught
        del conn.get_peer_certificate

    registry = listener._registry
    assert len(registry._pending) == 0
    assert len(registry._connections) == 0
    assert len(listener._conn_by_quic_id) == 0
    assert len(listener._handler_invoked_quic_ids) == 0
    assert len(listener._promotion_locks) == 0

    await listener.close()


@pytest.mark.trio
@pytest.mark.parametrize("shared_nursery", [False, True])
async def test_cancelled_listener_start_releases_transport_ownership(
    shared_nursery: bool,
) -> None:
    transport = make_transport()
    listeners = []
    async with trio.open_nursery() as nursery:
        if shared_nursery:
            transport.set_background_nursery(nursery)
        for _ in range(100):
            listener = transport.create_listener(_ignore)
            with trio.CancelScope() as scope:
                scope.cancel()
                await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"))
            assert scope.cancelled_caught
            listeners.append(listener)

        from trio.testing import wait_all_tasks_blocked

        await wait_all_tasks_blocked()
        # Check before closing the long-lived transport: its close would hide
        # listeners retained by failed startup.
        assert transport._listeners == []
        assert not transport._closed
        assert not nursery.cancel_scope.cancel_called
        assert all(not item.is_listening() for item in listeners)
        assert all(item._socket is None for item in listeners)
        assert all(item._close_complete.is_set() for item in listeners)
        if not shared_nursery:
            assert all(item._owned_stopped.is_set() for item in listeners)

        # Aborted listeners are closed and unregistered; reopening one would
        # create a listener the transport can no longer shut down.
        with pytest.raises(QUICListenError, match="closed"):
            await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"))

        refs = [weakref.ref(item) for item in listeners]
        listeners.clear()
        del listener
        gc.collect()
        assert all(ref() is None for ref in refs)

    await transport.close()
    assert len(transport._listeners) == 0


@pytest.mark.trio
async def test_close_before_listener_start_finishes_cleans_up():
    transport = make_transport()
    listener = transport.create_listener(_ignore)
    release = trio.Event()
    original_create_socket = listener._create_socket

    async def delayed_socket(host, port):
        await release.wait()
        return await original_create_socket(host, port)

    listener._create_socket = delayed_socket
    with trio.CancelScope() as scope:
        scope.cancel()
        await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"))
    assert scope.cancelled_caught

    await listener.close()
    assert listener._close_complete.is_set()
    release.set()

    from trio.testing import wait_all_tasks_blocked

    await wait_all_tasks_blocked()
    assert listener._owned_stopped is not None
    assert listener._owned_stopped.is_set()
    assert listener._socket is None
    assert not listener.is_listening()
    assert len(transport._listeners) == 0


@pytest.mark.trio
async def test_remove_by_address_purges_all_aliases_and_closes():
    transport = make_transport()
    listener = transport.create_listener(_ignore)

    for i in range(20):
        raw, conn = make_conn(transport)
        addr = ("127.0.0.1", 20000 + i)
        conn._remote_addr = addr
        cid = i.to_bytes(8, "big")
        alias = (i + 20).to_bytes(8, "big")
        await listener._registry.register_connection(cid, conn, addr)
        await listener._registry.add_connection_id(alias, cid, 1)
        listener._conn_by_quic_id[id(raw)] = conn
        await listener._remove_connection_by_addr(addr)
        assert conn.is_closed

    registry = listener._registry
    assert len(registry._connections) == 0
    assert len(registry._connection_id_to_addr) == 0
    assert len(registry._connection_sequences) == 0
    assert len(listener._conn_by_quic_id) == 0

    await listener.close()


@pytest.mark.trio
async def test_dial_after_transport_close_does_not_publish_connection():
    transport = make_transport()
    entered = 0
    all_entered = trio.Event()
    release = trio.Event()

    async def gated_connect(conn, nursery):
        nonlocal entered
        entered += 1
        if entered == 10:
            all_entered.set()
        await release.wait()
        conn._started = conn._established = True

    async def dial(i):
        with pytest.raises(QUICDialError):
            await transport.dial(
                Multiaddr(
                    f"/ip4/127.0.0.1/udp/{40000 + i}/quic-v1/p2p/{transport._peer_id}"
                )
            )

    with patch.object(QUICConnection, "connect", gated_connect):
        async with trio.open_nursery() as nursery:
            transport.set_background_nursery(nursery)
            for i in range(10):
                nursery.start_soon(dial, i)
            await all_entered.wait()
            await transport.close()
            release.set()

    await transport.close()
    assert transport._closed
    assert len(transport._connections) == 0

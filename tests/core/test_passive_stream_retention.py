"""Closed transport streams must release all connection-owned registries."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
import trio

from libp2p.abc import ISecureConn
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.rcmgr import Direction
from libp2p.stream_muxer.mplex.datastructures import StreamID
from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.stream import QUICStream, StreamDirection


@pytest.mark.trio
@pytest.mark.parametrize("remote_first", [False, True])
async def test_mplex_graceful_churn_releases_channel_registry(remote_first):
    async def write(data):
        pass

    conn = Mplex(
        cast(ISecureConn, SimpleNamespace(is_initiator=True, write=write)),
        ID(b"peer"),
    )
    for index in range(100):
        sid = StreamID(channel_id=index, is_initiator=True)
        stream = await conn._initialize_stream(sid, "test")
        # Graceful closure must still let the application drain queued data.
        await conn.streams_msg_channels[sid].send(b"buffered")
        if remote_first:
            await conn._handle_close(sid)
            await stream.close()
        else:
            await stream.close()
            await conn._handle_close(sid)
        assert await stream.read(8) == b"buffered"
        assert not conn.streams
        assert not conn.streams_msg_channels


@pytest.mark.trio
@pytest.mark.parametrize("cancel_send", [False, True])
async def test_mplex_local_reset_releases_both_registries(cancel_send):
    async def write(data):
        if cancel_send:
            await trio.sleep_forever()

    conn = Mplex(
        cast(ISecureConn, SimpleNamespace(is_initiator=True, write=write)),
        ID(b"peer"),
    )
    for index in range(100):
        sid = StreamID(channel_id=index, is_initiator=True)
        stream = await conn._initialize_stream(sid, "test")
        with trio.move_on_after(0.001) as scope:
            await stream.reset()
        assert scope.cancelled_caught == cancel_send
        assert not conn.streams
        assert not conn.streams_msg_channels


@pytest.mark.trio
@pytest.mark.parametrize("reset_timing", ["before", "during", "after"])
@pytest.mark.parametrize("direction", [Direction.INBOUND, Direction.OUTBOUND])
async def test_quic_remote_reset_releases_swarm_ownership(reset_timing, direction):
    opened, closed, removed = [], [], []
    released, slots = [], []

    async def notify_opened(stream):
        opened.append(stream)
        if reset_timing == "during":
            await stream.muxed_stream.handle_reset(0)

    async def notify_closed(stream):
        assert stream._direction == direction
        await Swarm.notify_closed_stream(swarm, stream)
        closed.append(stream)

    async def notify(*args):
        pass

    parent: Any = SimpleNamespace(
        _transport=SimpleNamespace(_config=QUICTransportConfig()),
        _remove_stream=removed.append,
        peer_id=ID(b"peer"),
        remote_peer_id=lambda: ID(b"peer"),
    )
    swarm: Any = SimpleNamespace(
        notify_opened_stream=notify_opened,
        notify_closed_stream=notify_closed,
        _resource_manager=SimpleNamespace(
            release_stream=lambda peer, direct: released.append((peer, direct))
        ),
        _stream_semaphore=SimpleNamespace(release=lambda: slots.append(True)),
        _notify=notify,
    )
    conn = SwarmConn(parent, swarm)
    for index in range(100):
        muxed = QUICStream(
            cast(QUICConnection, parent),
            index * 4,
            StreamDirection.OUTBOUND,
            ("127.0.0.1", 1),
        )
        if reset_timing == "before":
            await muxed.handle_reset(0)
        stream = await conn._add_stream(muxed, direction)
        if reset_timing == "after":
            await muxed.handle_reset(0)
        assert not conn.streams
        assert stream.swarm_conn is None
        assert len(opened) == len(closed) == index + 1
        # Repeated cleanup must not emit duplicate resource-release notifications.
        await muxed._cleanup_resources()
        assert len(closed) == index + 1
        assert len(released) == len(slots) == index + 1
        assert released[-1] == (str(parent.peer_id), direction)


@pytest.mark.trio
@pytest.mark.parametrize("remote_first", [False, True])
async def test_quic_fin_releases_owners_without_discarding_reply(remote_first):
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.connection import QuicConnection

    async def transmit():
        pass

    removed, closed = [], []
    parent = SimpleNamespace(
        _quic=QuicConnection(configuration=QuicConfiguration(is_client=True)),
        _transport=SimpleNamespace(_config=QUICTransportConfig()),
        _remove_stream=removed.append,
        _transmit=transmit,
        _signal_activity=lambda: None,
        remote_peer_id=lambda: ID(b"peer"),
    )
    stream = QUICStream(
        cast(QUICConnection, parent),
        0,
        StreamDirection.OUTBOUND,
        ("127.0.0.1", 1),
    )

    async def notify():
        closed.append(True)

    await stream.set_close_callback(notify)
    if remote_first:
        await stream.handle_data_received(b"reply", end_stream=True)
        assert not closed
        assert stream.can_write()
        await stream.close_write()
    else:
        await stream.close_write()
        assert not closed
        await stream.handle_data_received(b"reply", end_stream=True)
    assert removed == [0]
    assert closed == [True]
    assert await stream.read(5) == b"reply"

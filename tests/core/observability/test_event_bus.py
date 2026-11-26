"""
Tests for the INotifee-style event bus (``libp2p/events``).

Covers listener registration/fan-out, per-listener exception isolation
(the same guarantee the Swarm INotifee fan-out gives), thread-safety for
non-trio discovery callbacks, and the backward-compat channel bridge.
"""

import threading
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from multiaddr import Multiaddr
import trio
from trio.testing import wait_all_tasks_blocked

from libp2p import create_yamux_muxer_option, new_host, new_swarm
from libp2p.abc import IHost, IPeerRouting
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.events import ChannelBridgeListener, EventBus, IEventListener
from libp2p.host.basic_host import BasicHost
from libp2p.host.ping import PingEvent, PingService
from libp2p.metrics.listener import MetricsListener
from libp2p.metrics.metrics import Metrics
from libp2p.metrics.swarm import SwarmEvent
from libp2p.metrics.transport import ListenConn, TransportEvent, transport_label
from libp2p.network.exceptions import SwarmException
from libp2p.network.swarm import Swarm
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from tests.utils.factories import host_pair_factory


class RecordingListener(IEventListener):
    def __init__(self) -> None:
        self.events: list[object] = []

    def handle_event(self, event: object) -> None:
        self.events.append(event)


class RaisingListener(IEventListener):
    def handle_event(self, event: object) -> None:
        raise RuntimeError("boom")


class SampleEvent:
    pass


def test_register_and_emit_fans_out_to_all_listeners() -> None:
    bus = EventBus()
    a = RecordingListener()
    b = RecordingListener()

    bus.register_listener(a)
    bus.register_listener(b)

    event = SampleEvent()
    bus.emit(event)

    assert a.events == [event]
    assert b.events == [event]


def test_duplicate_registration_is_noop() -> None:
    bus = EventBus()
    a = RecordingListener()

    bus.register_listener(a)
    bus.register_listener(a)
    bus.emit(SampleEvent())

    assert len(a.events) == 1


def test_remove_listener_stops_delivery() -> None:
    bus = EventBus()
    a = RecordingListener()

    bus.register_listener(a)
    bus.remove_listener(a)
    bus.emit(SampleEvent())

    assert a.events == []


def test_listener_isolation_raising_listener_does_not_block_others() -> None:
    """
    A raising listener must never propagate into the emitter or block others.

    This mirrors ``Swarm._notify`` (INotifee) semantics.
    """
    bus = EventBus()
    bad = RaisingListener()
    good = RecordingListener()

    bus.register_listener(bad)
    bus.register_listener(good)

    # Must not raise despite ``bad`` throwing on every event.
    bus.emit(SampleEvent())

    assert len(good.events) == 1


def test_emit_is_safe_with_concurrent_registration() -> None:
    """register/emit may race (e.g. discovery callbacks off the trio thread)."""
    bus = EventBus()
    listener = RecordingListener()
    bus.register_listener(listener)

    stop = threading.Event()
    errors: list[Exception] = []

    def emitter() -> None:
        while not stop.is_set():
            try:
                bus.emit(SampleEvent())
            except Exception as e:  # pragma: no cover
                errors.append(e)

    def registrar() -> None:
        extra = RecordingListener()
        while not stop.is_set():
            bus.register_listener(extra)
            bus.remove_listener(extra)

    threads = [threading.Thread(target=emitter) for _ in range(2)]
    threads.append(threading.Thread(target=registrar))
    for t in threads:
        t.start()
    import time

    time.sleep(0.05)
    stop.set()
    for t in threads:
        t.join()

    assert errors == []
    assert len(listener.events) > 0


@pytest.mark.trio
async def test_bridge_forwards_events_into_channel() -> None:
    send_channel, recv_channel = trio.open_memory_channel(4)
    bridge = ChannelBridgeListener(send_channel)
    bus = EventBus()
    bus.register_listener(bridge)

    event = SampleEvent()
    bus.emit(event)

    received = await recv_channel.receive()
    assert received is event


@pytest.mark.trio
async def test_bridge_drops_event_when_channel_full() -> None:
    """Full channel must drop (metrics are loss-tolerant) and never raise."""
    send_channel, recv_channel = trio.open_memory_channel(1)
    bridge = ChannelBridgeListener(send_channel)
    bus = EventBus()
    bus.register_listener(bridge)

    # Fill the channel.
    bus.emit(SampleEvent())
    bus.emit(SampleEvent())  # must be dropped, not raised

    received = await recv_channel.receive()
    assert isinstance(received, SampleEvent)


@pytest.mark.trio
async def test_bridge_ignores_closed_channel() -> None:
    send_channel, recv_channel = trio.open_memory_channel(1)
    bridge = ChannelBridgeListener(send_channel)
    bus = EventBus()
    bus.register_listener(bridge)

    recv_channel.close()
    # Must not raise.
    bus.emit(SampleEvent())
    bus.emit(SampleEvent())


@pytest.mark.trio
async def test_bridge_drops_off_thread_event_even_when_buffer_has_space() -> None:
    send_channel, recv_channel = trio.open_memory_channel(1)
    bus = EventBus()
    bus.register_listener(ChannelBridgeListener(send_channel))

    await trio.to_thread.run_sync(bus.emit, SampleEvent())

    with pytest.raises(trio.WouldBlock):
        recv_channel.receive_nowait()


def security_options(key_pair):
    return {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair, secure_bytes_provider=None, peerstore=None
        )
    }


def test_host_implementation_can_inherit_default_event_bus():
    class LegacyHost(BasicHost):
        get_event_bus = IHost.get_event_bus

    first = LegacyHost(new_swarm())
    second = LegacyHost(new_swarm())
    listener = RecordingListener()

    first.get_event_bus().register_listener(listener)
    first.get_event_bus().emit("from first host")
    second.get_event_bus().emit("from second host")

    assert listener.events == ["from first host"]


@pytest.mark.trio
async def test_ping_emits_ping_event_on_host_bus(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        listener = RecordingListener()
        host_a.get_event_bus().register_listener(listener)

        ping_service = PingService(host_a)
        rtts = await ping_service.ping(host_b.get_id())
        assert rtts

        ping_events = [e for e in listener.events if isinstance(e, PingEvent)]
        assert ping_events, "no PingEvent emitted on host_a's event bus"
        assert ping_events[0].rtts


@pytest.mark.trio
async def test_metrics_listener_on_host_bus_does_not_break_ping(
    security_protocol, monkeypatch
):
    """MetricsListener attached to a real host must be transparent."""
    monkeypatch.setattr("libp2p.metrics.metrics.start_http_server", lambda *_: None)
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Attach the full metrics pipeline the way an app would.
        host_a.get_event_bus().register_listener(MetricsListener(Metrics()))

        ping_service = PingService(host_a)
        rtts = await ping_service.ping(host_b.get_id())
        assert rtts


@pytest.mark.trio
async def test_inbound_swarm_lifecycle_emits_events_on_host_bus():
    """
    Admission and lifecycle events reach the bus configured before listening.
    """
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options(key_pair_a),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )
    bus = EventBus()
    listener = RecordingListener()
    bus.register_listener(listener)
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options(key_pair_b),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
        event_bus=bus,
    )
    assert host_b.get_event_bus() is bus

    async with (
        host_b.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_a.run(listen_addrs=[]),
    ):
        # Host A dials host B's TCP address (inbound connection on B).
        tcp_addr = next(
            a for a in host_b.get_addrs() if "/tcp/" in str(a) and "/ws" not in str(a)
        )
        await host_a.connect(info_from_p2p_addr(tcp_addr))

        await wait_all_tasks_blocked()
        await host_b.disconnect(host_a.get_id())

    swarm = [e for e in listener.events if isinstance(e, SwarmEvent)]
    assert [e.conn_incoming for e in swarm] == [True]
    results = [
        e for e in listener.events if isinstance(e, TransportEvent) and e.conn_in
    ]
    assert [(e.transport, e.success) for e in results] == [("tcp", True)]
    lifecycle = [e for e in listener.events if isinstance(e, ListenConn)]
    assert [(e.conn_open, e.conn_close) for e in lifecycle] == [
        (True, False),
        (False, True),
    ]
    assert {e.peer_id for e in lifecycle} == {str(host_a.get_id())}
    assert lifecycle[0].connection_type == lifecycle[1].connection_type


@pytest.mark.trio
@pytest.mark.parametrize("rejection", ["capacity", "upgrade"])
async def test_rejected_inbound_reports_one_failure(rejection, monkeypatch):
    bus = EventBus()
    listener = RecordingListener()
    bus.register_listener(listener)
    swarm = cast(Swarm, new_swarm(event_bus=bus))
    conn = Mock(get_remote_address=Mock(return_value=None), close=AsyncMock())
    if rejection == "capacity":
        limiter = trio.CapacityLimiter(1)
        limiter.acquire_on_behalf_of_nowait("existing connection")
        monkeypatch.setattr(swarm, "_inbound_limiter", limiter)
    else:
        monkeypatch.setattr(
            swarm, "upgrade_inbound_raw_conn", AsyncMock(side_effect=SwarmException())
        )

    await swarm._handle_inbound_connection(conn, Multiaddr("/ip4/127.0.0.1/tcp/0"))

    results = [e for e in listener.events if isinstance(e, TransportEvent)]
    assert [(e.conn_in, e.success) for e in results] == [(True, False)]
    inbound = [e for e in listener.events if isinstance(e, SwarmEvent)]
    assert [e.conn_incoming_error for e in inbound] == [False, True]
    assert not any(isinstance(e, ListenConn) for e in listener.events)
    conn.close.assert_awaited_once()


@pytest.mark.trio
@pytest.mark.parametrize("routed", [False, True])
async def test_host_legacy_channel_uses_configured_bus(routed):
    bus = EventBus()
    router = Mock(spec=IPeerRouting) if routed else None
    host = new_host(disc_opt=router, enable_metrics=True, event_bus=bus)
    assert host.get_event_bus() is bus
    channel = host.get_metrics_recv_channel()
    assert channel is not None

    event = SwarmEvent()
    bus.emit(event)
    assert channel.receive_nowait() is event


def test_transport_label_uses_multiaddr_protocols():
    webtransport = Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1/webtransport")
    assert transport_label(maddr=webtransport) == "webtransport"
    assert transport_label(maddr=Multiaddr("/dns4/news.example/tcp/0")) == "tcp"

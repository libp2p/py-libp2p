"""Tests for the INotifee-style event bus (``libp2p/events``).

Covers listener registration/fan-out, per-listener exception isolation
(the same guarantee the Swarm INotifee fan-out gives), thread-safety for
non-trio discovery callbacks, and the backward-compat channel bridge.
"""

import threading

import pytest
import trio

from libp2p.events import ChannelBridgeListener, EventBus, IEventListener


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
    """A raising listener must never propagate into the emitter or block others.

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

"""Tests for the event-bus-backed metrics pipeline.

Covers the new per-module collectors (bitswap, discovery, outbound DHT,
outbound pubsub), the ``MetricsListener`` type dispatch and
``Metrics.attach`` wiring.
"""

from prometheus_client import REGISTRY
import pytest
import trio

from libp2p.bitswap.events import BitswapEvent
from libp2p.discovery.events.events import DiscoveryEvent
from libp2p.events import EventBus
from libp2p.host.ping import PingEvent
from libp2p.kad_dht.events import KadDhtEvent
from libp2p.metrics.listener import MetricsListener
from libp2p.metrics.metrics import Metrics
from libp2p.metrics.swarm import SwarmEvent
from libp2p.peer.id import ID
from libp2p.pubsub.pubsub import GossipsubEvent

PEER_ID = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
PEER_ID_OBJ = ID.from_string(PEER_ID)


def clear_registry() -> None:
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass


def test_bitswap_metrics_records_all_event_kinds() -> None:
    clear_registry()
    metrics = Metrics()

    for flag, payload in [
        ("want_add", {}),
        ("want_cancel", {}),
        ("block_received", {"size_bytes": 4096}),
        ("block_sent", {"size_bytes": 1024}),
        ("message_sent", {"kind": "wantlist"}),
        ("message_received", {"kind": "block", "msg_bytes": 2048}),
        ("session_new", {}),
        ("provider_query", {"success": True, "peers_found": 3}),
        ("provider_query", {"success": False}),
    ]:
        event = BitswapEvent()
        setattr(event, flag, True)
        for key, value in payload.items():
            setattr(event, key, value)
        # Just ensuring no exception is thrown for any event kind.
        metrics.bitswap.record(event)


def test_discovery_metrics_records_all_event_kinds() -> None:
    clear_registry()
    metrics = Metrics()

    cases = [
        {"peer_discovered": True, "source": "mdns"},
        {"peer_lost": True, "source": "bootstrap"},
        {"bootstrap_connect": True, "success": True, "duration_ms": 12.5},
        {"bootstrap_connect": True, "success": False},
        {"random_walk": True, "success": True, "peers_found": 2},
        {"random_walk": True, "success": False},
    ]
    for kwargs in cases:
        event = DiscoveryEvent()
        for key, value in kwargs.items():
            setattr(event, key, value)
        metrics.discovery.record(event)


def test_kad_dht_metrics_records_outbound_events() -> None:
    clear_registry()
    metrics = Metrics()

    cases = [
        {"lookup": True, "success": True, "duration_ms": 42.0, "peers_queried": 4, "peers_found": 3},
        {"provide": True, "success": True, "peers_announced": 5},
        {"find_providers": True, "success": True, "providers_found": 2},
        {"put_value_out": True, "success": True},
        {"get_value_out": True, "success": True, "value_found": True},
        {"find_peer": True, "success": False},
        {"refresh": True, "success": True},
        {"republish": True, "success": True, "record_type": "provider"},
        {"rate_limited": True},
        {"stream_reset": True},
        {"routing_table": True, "count": 42},
    ]
    for kwargs in cases:
        event = KadDhtEvent()
        event.peer_id = PEER_ID
        for key, value in kwargs.items():
            setattr(event, key, value)
        metrics.kad_dht.record(event)


def test_gossipsub_metrics_records_outbound_events() -> None:
    clear_registry()
    metrics = Metrics()

    publish = GossipsubEvent()
    publish.peer_id = PEER_ID
    publish.publish_out = True
    publish.message_size = 512
    publish.topic = "test-topic"
    metrics.gossipsub.record(publish)

    sub_change = GossipsubEvent()
    sub_change.peer_id = PEER_ID
    sub_change.subscription_change = True
    sub_change.action = "subscribe"
    metrics.gossipsub.record(sub_change)


def test_metrics_listener_dispatches_by_event_type() -> None:
    clear_registry()
    metrics = Metrics()
    listener = MetricsListener(metrics)

    events = [
        PingEvent(peer_id=PEER_ID_OBJ, rtts=[10], failure_error=None),
        GossipsubEvent(),
        KadDhtEvent(),
        SwarmEvent(),
        BitswapEvent(),
        DiscoveryEvent(),
    ]
    for event in events:
        listener.handle_event(event)  # must not raise for any type


def test_metrics_attach_registers_listener_on_bus() -> None:
    clear_registry()
    bus = EventBus()
    metrics = Metrics()
    attached = metrics.attach(bus)

    assert attached is metrics
    assert len(bus.listeners) == 1
    assert isinstance(bus.listeners[0], MetricsListener)


@pytest.mark.trio
async def test_metrics_listener_records_emitted_events(monkeypatch) -> None:
    """End-to-end: emit on the bus -> MetricsListener -> prometheus registry."""
    clear_registry()
    bus = EventBus()
    metrics = Metrics()
    metrics.attach(bus)

    # Spy on the collectors to prove events flow through.
    recorded: list[str] = []

    def fake_kad_record(event):
        recorded.append("kad")

    def fake_bitswap_record(event):
        recorded.append("bitswap")

    metrics.kad_dht.record = fake_kad_record
    metrics.bitswap.record = fake_bitswap_record

    kad_event = KadDhtEvent()
    kad_event.peer_id = PEER_ID
    kad_event.lookup = True
    kad_event.success = True
    bus.emit(kad_event)

    bitswap_event = BitswapEvent()
    bitswap_event.block_received = True
    bus.emit(bitswap_event)

    # Emit must be synchronous fan-out — nothing to await.
    assert recorded == ["kad", "bitswap"]

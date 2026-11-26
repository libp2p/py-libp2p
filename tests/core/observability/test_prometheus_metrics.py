import pytest
from prometheus_client import REGISTRY, CollectorRegistry
import trio

from libp2p.bitswap.events import BitswapEvent
from libp2p.discovery.events.events import DiscoveryEvent
from libp2p.events import EventBus
from libp2p.host.ping import PingEvent
from libp2p.kad_dht.events import KadDhtEvent
from libp2p.metrics.listener import MetricsListener
from libp2p.metrics.metrics import Metrics, find_available_port
from libp2p.metrics.swarm import SwarmEvent
from libp2p.peer.id import ID
from libp2p.pubsub.pubsub import GossipsubEvent
from libp2p.rcmgr import new_resource_manager


def test_find_available_port_returns_free_port() -> None:
    port = find_available_port(8000)
    assert isinstance(port, int)
    assert port >= 8000


def test_ping_metrics_records_rtt() -> None:
    metrics = Metrics()

    event = PingEvent(
        peer_id=ID.from_string("12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"),
        rtts=[100, 200],
        failure_error=None,
    )

    invalid_event = PingEvent(
        peer_id=ID.from_string("12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"),
        rtts=None,
        failure_error=None,
    )

    # Just ensuring no error throw for valid Ping events
    metrics.ping.record(event)

    with pytest.raises(ValueError):
        metrics.ping.record(invalid_event)


def test_gossipsub_metrics_records_events() -> None:
    metrics = Metrics()

    event = GossipsubEvent()
    event.peer_id = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
    event.message_size = 512
    event.subopts = True

    # Just ensuring no error is thrown
    metrics.gossipsub.record(event)


def test_kad_dht_metrics_records_all_events() -> None:
    metrics = Metrics()

    event = KadDhtEvent()
    event.peer_id = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
    event.inbound = True
    event.find_node = True

    # Just ensuring no exception is thrown
    metrics.kad_dht.record(event)


def test_swarm_metrics_records_all_events() -> None:
    metrics = Metrics()

    event = SwarmEvent()
    event.peer_id = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
    event.conn_incoming = True
    event.conn_incoming_error = True

    # Just ensuring no exception is thrown
    metrics.swarm.record(event)


@pytest.mark.trio
async def test_metrics_pipeline_dispatches_legacy_and_new_events(monkeypatch) -> None:
    metrics = Metrics()

    # --- mock prometheus server ---
    monkeypatch.setattr(
        "libp2p.metrics.metrics.start_http_server",
        lambda *_: None,
    )

    recorded: list[object] = []
    monkeypatch.setattr(metrics.ping, "record", recorded.append)
    monkeypatch.setattr(metrics.bitswap, "record", recorded.append)

    ping = PingEvent(
        peer_id=ID.from_string("12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"),
        rtts=[100],
        failure_error=None,
    )
    bitswap = BitswapEvent()
    bitswap.block_received = True

    send_channel, recv_channel = trio.open_memory_channel[object](2)
    async with send_channel:
        send_channel.send_nowait(ping)
        send_channel.send_nowait(bitswap)
    await metrics.start_prometheus_server(recv_channel)

    assert recorded == [ping, bitswap]


PEER_ID = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
PEER_ID_OBJ = ID.from_string(PEER_ID)


def test_bitswap_metrics_records_all_event_kinds() -> None:
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
    metrics = Metrics()

    cases = [
        {
            "lookup": True,
            "success": True,
            "duration_ms": 42.0,
            "peers_queried": 4,
            "peers_found": 3,
        },
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
    bus = EventBus()
    metrics = Metrics()
    attached = metrics.attach(bus).attach(bus)

    assert attached is metrics
    assert len(bus.listeners) == 1
    assert isinstance(bus.listeners[0], MetricsListener)

    before = REGISTRY.get_sample_value("swarm_dial_attempt_total")
    assert before is not None
    event = SwarmEvent()
    event.dial_attempt = True
    bus.emit(event)
    assert REGISTRY.get_sample_value("swarm_dial_attempt_total") == before + 1


def test_metrics_replaces_resource_manager_collector(monkeypatch) -> None:
    registry = CollectorRegistry(auto_describe=True)
    metrics = Metrics()
    monkeypatch.setattr("libp2p.metrics.metrics.REGISTRY", registry)
    monkeypatch.setattr(metrics, "rcmgr", None)
    first = new_resource_manager()
    second = new_resource_manager()
    assert first.metrics is not None
    first.metrics.allow_conn("inbound")

    labels = {"dir": "inbound"}
    assert Metrics(first) is metrics
    assert registry.get_sample_value("libp2p_rcmgr_connections", labels) == 1
    assert Metrics(second) is metrics
    assert registry.get_sample_value("libp2p_rcmgr_connections", labels) == 0


@pytest.mark.trio
async def test_metrics_listener_records_emitted_events(monkeypatch) -> None:
    """End-to-end: emit on the bus -> MetricsListener -> prometheus registry."""
    bus = EventBus()
    metrics = Metrics()
    metrics.attach(bus)

    # Spy on the collectors to prove events flow through.
    recorded: list[str] = []

    def fake_kad_record(event):
        recorded.append("kad")

    def fake_bitswap_record(event):
        recorded.append("bitswap")

    monkeypatch.setattr(metrics.kad_dht, "record", fake_kad_record)
    monkeypatch.setattr(metrics.bitswap, "record", fake_bitswap_record)

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

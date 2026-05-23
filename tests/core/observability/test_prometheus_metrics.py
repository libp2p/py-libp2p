import pytest
from prometheus_client import REGISTRY
import trio

from libp2p.host.ping import PingEvent
from libp2p.kad_dht.kad_dht import KadDhtEvent
from libp2p.metrics.metrics import Metrics, find_available_port
from libp2p.metrics.swarm import SwarmEvent
from libp2p.peer.id import ID
from libp2p.pubsub.pubsub import GossipsubEvent


def clear_registry():
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass


def test_find_available_port_returns_free_port() -> None:
    port = find_available_port(8000)
    assert isinstance(port, int)
    assert port >= 8000


def test_ping_metrics_records_rtt() -> None:
    clear_registry()
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
    clear_registry()
    metrics = Metrics()

    event = GossipsubEvent()
    event.peer_id = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
    event.message_size = 512
    event.subopts = True

    # Just ensuring no error is thrown
    metrics.gossipsub.record(event)


def test_kad_dht_metrics_records_all_events() -> None:
    clear_registry()
    metrics = Metrics()

    event = KadDhtEvent()
    event.peer_id = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
    event.inbound = True
    event.find_node = True

    # Just ensuring no exception is thrown
    metrics.kad_dht.record(event)


def test_swarm_metrics_records_all_events() -> None:
    clear_registry()
    metrics = Metrics()

    event = SwarmEvent()
    event.peer_id = "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
    event.conn_incoming = True
    event.conn_incoming_error = True

    # Just ensuring no exception is thrown
    metrics.swarm.record(event)


@pytest.mark.trio
async def test_metrics_pipeline_dispatches_ping(monkeypatch) -> None:
    clear_registry()
    metrics = Metrics()

    # --- mock prometheus server ---
    monkeypatch.setattr(
        "libp2p.metrics.metrics.start_http_server",
        lambda *_: None,
    )

    # --- spy on ping.record ---
    called = {"ping": False}

    def fake_ping_record(event):
        called["ping"] = True

    metrics.ping.record = fake_ping_record

    send_channel, recv_channel = trio.open_memory_channel(1)

    async def run():
        await metrics.start_prometheus_server(recv_channel)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(run)

        event = PingEvent(
            peer_id=ID.from_string(
                "12D3KooWRcqGSY7VJKZihipeo3NMikpWb185DxA5ZQreJ364ihEx"
            ),
            rtts=[100],
            failure_error=None,
        )

        await send_channel.send(event)

        # give event loop time
        await trio.sleep(0.1)

        nursery.cancel_scope.cancel()

    assert called["ping"] is True

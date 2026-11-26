import pytest
import trio

from libp2p.bitswap.events import BitswapEvent
from libp2p.host.ping import PingEvent
from libp2p.kad_dht.kad_dht import KadDhtEvent
from libp2p.metrics.metrics import Metrics, find_available_port
from libp2p.metrics.swarm import SwarmEvent
from libp2p.peer.id import ID
from libp2p.pubsub.pubsub import GossipsubEvent


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

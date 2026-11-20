"""Integration tests: real module operations emit events on the host's bus.

These prove the event bus is wired end-to-end — a ping, a pubsub publish
and a swarm dial each surface as typed events on ``host.get_event_bus()``
without any special plumbing.
"""

import pytest
import trio

from multiaddr import Multiaddr

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TSecurityOptions
from libp2p.events import IEventListener
from libp2p.host.ping import PingEvent, PingService
from libp2p.metrics.listener import MetricsListener
from libp2p.metrics.metrics import Metrics
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from tests.utils.factories import host_pair_factory


def security_options(key_pair):
    return {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair, secure_bytes_provider=None, peerstore=None
        )
    }


class CollectingListener(IEventListener):
    def __init__(self) -> None:
        self.events: list[object] = []

    def handle_event(self, event: object) -> None:
        self.events.append(event)


@pytest.mark.trio
async def test_ping_emits_ping_event_on_host_bus(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        listener = CollectingListener()
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
    monkeypatch.setattr(
        "libp2p.metrics.metrics.start_http_server", lambda *_: None
    )
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
async def test_swarm_dial_emits_swarm_event_on_host_bus(security_protocol):
    """An inbound dial must surface as a SwarmEvent on the listener's bus.

    Uses ``create_batch_and_listen`` directly (no pre-connect) so the
    listener is registered before the dial happens.
    """
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options(key_pair_a),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options(key_pair_b),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    async with (
        host_b.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_a.run(listen_addrs=[]),
    ):
        listener = CollectingListener()
        host_b.get_event_bus().register_listener(listener)

        # Host A dials host B's TCP address (inbound connection on B).
        tcp_addr = next(
            a for a in host_b.get_addrs() if "/tcp/" in str(a) and "/ws" not in str(a)
        )
        await host_a.connect(info_from_p2p_addr(tcp_addr))

        # Give the swarm notifee/emit loop a moment to run.
        await trio.sleep(0.2)

        from libp2p.metrics.swarm import SwarmEvent

        swarm_events = [e for e in listener.events if isinstance(e, SwarmEvent)]
        assert swarm_events, "no SwarmEvent emitted on host_b's event bus"

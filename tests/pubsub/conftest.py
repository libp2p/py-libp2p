import asyncio
from typing import NamedTuple

import pytest

from multiaddr import Multiaddr

from libp2p import new_node

from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub

from .configs import (
    FLOODSUB_PROTOCOL_ID,
    GOSSIPSUB_PROTOCOL_ID,
    LISTEN_MADDR,
)


# pylint: disable=redefined-outer-name

@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts):
    _hosts = await asyncio.gather(*[
        new_node(transport_opt=[str(LISTEN_MADDR)])
        for _ in range(num_hosts)
    ])
    await asyncio.gather(*[
        _host.get_network().listen(LISTEN_MADDR)
        for _host in _hosts
    ])
    yield _hosts
    # Clean up
    listeners = []
    for _host in _hosts:
        for listener in _host.get_network().listeners.values():
            listener.server.close()
            listeners.append(listener)
    await asyncio.gather(*[
        listener.server.wait_closed()
        for listener in listeners
    ])


@pytest.fixture
def floodsubs(num_hosts):
    return tuple(
        FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])
        for _ in range(num_hosts)
    )


class GossipsubParams(NamedTuple):
    degree: int = 10
    degree_low: int = 9
    degree_high: int = 11
    fanout_ttl: int = 30
    gossip_window: int = 3
    gossip_history: int = 5
    heartbeat_interval: float = 0.5


@pytest.fixture
def gossipsub_params():
    return GossipsubParams()


@pytest.fixture
def gossipsubs(num_hosts, gossipsub_params):
    yield tuple(
        GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            **gossipsub_params._asdict(),
        )
        for _ in range(num_hosts)
    )
    # TODO: Clean up


def _make_pubsubs(hosts, pubsub_routers):
    if len(pubsub_routers) != len(hosts):
        raise ValueError(
            f"lenght of pubsub_routers={pubsub_routers} should be equaled to "
            f"hosts={hosts}"
        )
    return tuple(
        Pubsub(
            host=host,
            router=router,
            my_id=host.get_id(),
        )
        for host, router in zip(hosts, pubsub_routers)
    )


@pytest.fixture
def pubsubs_fsub(hosts, floodsubs):
    _pubsubs_gsub = _make_pubsubs(hosts, floodsubs)
    yield _pubsubs_gsub
    # TODO: Clean up


@pytest.fixture
def pubsubs_gsub(hosts, gossipsubs):
    _pubsubs_gsub = _make_pubsubs(hosts, gossipsubs)
    yield _pubsubs_gsub
    # TODO: Clean up

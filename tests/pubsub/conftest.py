import asyncio

import pytest

from tests.configs import LISTEN_MADDR

from .configs import GOSSIPSUB_PARAMS
from .factories import FloodsubFactory, GossipsubFactory, HostFactory, PubsubFactory


@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts):
    _hosts = HostFactory.create_batch(num_hosts)
    await asyncio.gather(*[_host.get_network().listen(LISTEN_MADDR) for _host in _hosts])
    yield _hosts
    # Clean up
    listeners = []
    for _host in _hosts:
        for listener in _host.get_network().listeners.values():
            listener.server.close()
            listeners.append(listener)
    await asyncio.gather(*[listener.server.wait_closed() for listener in listeners])


@pytest.fixture
def floodsubs(num_hosts):
    return FloodsubFactory.create_batch(num_hosts)


@pytest.fixture
def gossipsub_params():
    return GOSSIPSUB_PARAMS


@pytest.fixture
def gossipsubs(num_hosts, gossipsub_params):
    yield GossipsubFactory.create_batch(num_hosts, **gossipsub_params._asdict())
    # TODO: Clean up


def _make_pubsubs(hosts, pubsub_routers, cache_size):
    if len(pubsub_routers) != len(hosts):
        raise ValueError(
            f"lenght of pubsub_routers={pubsub_routers} should be equaled to the "
            f"length of hosts={len(hosts)}"
        )
    return tuple(
        PubsubFactory(host=host, router=router, cache_size=cache_size)
        for host, router in zip(hosts, pubsub_routers)
    )


@pytest.fixture
def pubsub_cache_size():
    return None  # default


@pytest.fixture
def pubsubs_fsub(hosts, floodsubs, pubsub_cache_size):
    _pubsubs_fsub = _make_pubsubs(hosts, floodsubs, pubsub_cache_size)
    yield _pubsubs_fsub
    # TODO: Clean up


@pytest.fixture
def pubsubs_gsub(hosts, gossipsubs, pubsub_cache_size):
    _pubsubs_gsub = _make_pubsubs(hosts, gossipsubs, pubsub_cache_size)
    yield _pubsubs_gsub
    # TODO: Clean up

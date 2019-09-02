import asyncio

import pytest

from .configs import LISTEN_MADDR
from .factories import FloodsubFactory, GossipsubFactory, HostFactory, PubsubFactory
from .pubsub.configs import GOSSIPSUB_PARAMS


@pytest.fixture
def is_host_secure():
    return False


@pytest.fixture
def num_hosts():
    return 3


@pytest.fixture
async def hosts(num_hosts, is_host_secure):
    _hosts = HostFactory.create_batch(num_hosts, is_secure=is_host_secure)
    await asyncio.gather(
        *[_host.get_network().listen(LISTEN_MADDR) for _host in _hosts]
    )
    try:
        yield _hosts
    finally:
        # TODO: It's possible that `close` raises exceptions currently,
        #   due to the connection reset things. Though we don't care much about that when
        #   cleaning up the tasks, it is probably better to handle the exceptions properly.
        await asyncio.gather(
            *[_host.close() for _host in _hosts], return_exceptions=True
        )


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

import pytest

from tests.factories import FloodsubFactory, GossipsubFactory, PubsubFactory
from tests.pubsub.configs import GOSSIPSUB_PARAMS


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

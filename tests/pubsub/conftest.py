import pytest

from libp2p.tools.constants import GOSSIPSUB_PARAMS
from libp2p.tools.factories import FloodsubFactory, GossipsubFactory, PubsubFactory


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
def gossipsub_params():
    return GOSSIPSUB_PARAMS


@pytest.fixture
def pubsubs_fsub(num_hosts, hosts, pubsub_cache_size):
    floodsubs = FloodsubFactory.create_batch(num_hosts)
    _pubsubs_fsub = _make_pubsubs(hosts, floodsubs, pubsub_cache_size)
    yield _pubsubs_fsub
    # TODO: Clean up


@pytest.fixture
def pubsubs_gsub(num_hosts, hosts, pubsub_cache_size, gossipsub_params):
    gossipsubs = GossipsubFactory.create_batch(num_hosts, **gossipsub_params._asdict())
    _pubsubs_gsub = _make_pubsubs(hosts, gossipsubs, pubsub_cache_size)
    yield _pubsubs_gsub
    # TODO: Clean up

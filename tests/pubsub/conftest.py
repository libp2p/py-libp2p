import pytest

from libp2p.tools.constants import GOSSIPSUB_PARAMS
from libp2p.tools.factories import FloodsubFactory, GossipsubFactory, PubsubFactory


@pytest.fixture
def is_strict_signing():
    return False


def _make_pubsubs(hosts, pubsub_routers, cache_size, is_strict_signing):
    if len(pubsub_routers) != len(hosts):
        raise ValueError(
            f"lenght of pubsub_routers={pubsub_routers} should be equaled to the "
            f"length of hosts={len(hosts)}"
        )
    return tuple(
        PubsubFactory(
            host=host,
            router=router,
            cache_size=cache_size,
            strict_signing=is_strict_signing,
        )
        for host, router in zip(hosts, pubsub_routers)
    )


@pytest.fixture
def pubsub_cache_size():
    return None  # default


@pytest.fixture
def gossipsub_params():
    return GOSSIPSUB_PARAMS


@pytest.fixture
def pubsubs_fsub(num_hosts, hosts, pubsub_cache_size, is_strict_signing):
    floodsubs = FloodsubFactory.create_batch(num_hosts)
    _pubsubs_fsub = _make_pubsubs(
        hosts, floodsubs, pubsub_cache_size, is_strict_signing
    )
    yield _pubsubs_fsub
    # TODO: Clean up


@pytest.fixture
def pubsubs_gsub(
    num_hosts, hosts, pubsub_cache_size, gossipsub_params, is_strict_signing
):
    gossipsubs = GossipsubFactory.create_batch(num_hosts, **gossipsub_params._asdict())
    _pubsubs_gsub = _make_pubsubs(
        hosts, gossipsubs, pubsub_cache_size, is_strict_signing
    )
    yield _pubsubs_gsub
    # TODO: Clean up

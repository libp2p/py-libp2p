import pytest

from libp2p.tools.constants import GOSSIPSUB_PARAMS
from libp2p.tools.factories import FloodsubFactory, GossipsubFactory, PubsubFactory


@pytest.fixture
def pubsub_cache_size():
    return None  # default


@pytest.fixture
def gossipsub_params():
    return GOSSIPSUB_PARAMS


# @pytest.fixture
# def pubsubs_gsub(num_hosts, hosts, pubsub_cache_size, gossipsub_params):
#     gossipsubs = GossipsubFactory.create_batch(num_hosts, **gossipsub_params._asdict())
#     _pubsubs_gsub = _make_pubsubs(hosts, gossipsubs, pubsub_cache_size)
#     yield _pubsubs_gsub
#     # TODO: Clean up

import factory

from libp2p import initialize_default_swarm
from libp2p.host.basic_host import BasicHost
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from tests.configs import (
    FLOODSUB_PROTOCOL_ID,
    GOSSIPSUB_PARAMS,
    GOSSIPSUB_PROTOCOL_ID,
    LISTEN_MADDR,
)
from tests.utils import generate_new_private_key


def swarm_factory():
    private_key = generate_new_private_key()
    return initialize_default_swarm(private_key, transport_opt=[str(LISTEN_MADDR)])


class HostFactory(factory.Factory):
    class Meta:
        model = BasicHost

    network = factory.LazyFunction(swarm_factory)


class FloodsubFactory(factory.Factory):
    class Meta:
        model = FloodSub

    protocols = (FLOODSUB_PROTOCOL_ID,)


class GossipsubFactory(factory.Factory):
    class Meta:
        model = GossipSub

    protocols = (GOSSIPSUB_PROTOCOL_ID,)
    degree = GOSSIPSUB_PARAMS.degree
    degree_low = GOSSIPSUB_PARAMS.degree_low
    degree_high = GOSSIPSUB_PARAMS.degree_high
    time_to_live = GOSSIPSUB_PARAMS.time_to_live
    gossip_window = GOSSIPSUB_PARAMS.gossip_window
    gossip_history = GOSSIPSUB_PARAMS.gossip_history
    heartbeat_interval = GOSSIPSUB_PARAMS.heartbeat_interval


class PubsubFactory(factory.Factory):
    class Meta:
        model = Pubsub

    host = factory.SubFactory(HostFactory)
    router = None
    my_id = factory.LazyAttribute(lambda obj: obj.host.get_id())
    cache_size = None

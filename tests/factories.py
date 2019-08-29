from typing import Dict

import factory

from libp2p import generate_new_rsa_identity, initialize_default_swarm
from libp2p.crypto.keys import KeyPair
from libp2p.host.basic_host import BasicHost
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.security.secio.transport import ID, Transport
from libp2p.typing import TProtocol
from tests.pubsub.configs import (
    FLOODSUB_PROTOCOL_ID,
    GOSSIPSUB_PARAMS,
    GOSSIPSUB_PROTOCOL_ID,
)


def security_transport_factory(
    is_secure: bool, key_pair: KeyPair
) -> Dict[TProtocol, BaseSecureTransport]:
    protocol_id: TProtocol
    security_transport: BaseSecureTransport
    if not is_secure:
        protocol_id = PLAINTEXT_PROTOCOL_ID
        security_transport = InsecureTransport(key_pair)
    else:
        protocol_id = ID
        security_transport = Transport(key_pair)
    return {protocol_id: security_transport}


def swarm_factory(is_secure: bool):
    key_pair = generate_new_rsa_identity()
    sec_opt = security_transport_factory(is_secure, key_pair)
    return initialize_default_swarm(key_pair, sec_opt=sec_opt)


class HostFactory(factory.Factory):
    class Meta:
        model = BasicHost

    class Params:
        is_secure = False

    network = factory.LazyAttribute(lambda o: swarm_factory(o.is_secure))


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

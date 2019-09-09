import asyncio
from typing import Dict, Tuple

import factory

from libp2p import generate_new_rsa_identity, initialize_default_swarm
from libp2p.crypto.keys import KeyPair
from libp2p.host.basic_host import BasicHost
from libp2p.host.host_interface import IHost
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream
from libp2p.typing import TProtocol
from tests.configs import LISTEN_MADDR
from tests.pubsub.configs import (
    FLOODSUB_PROTOCOL_ID,
    GOSSIPSUB_PARAMS,
    GOSSIPSUB_PROTOCOL_ID,
)
from tests.utils import connect


def security_transport_factory(
    is_secure: bool, key_pair: KeyPair
) -> Dict[TProtocol, BaseSecureTransport]:
    if not is_secure:
        return {PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)}
    else:
        return {secio.ID: secio.Transport(key_pair)}


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

    @classmethod
    async def create_and_listen(cls) -> IHost:
        host = cls()
        await host.get_network().listen(LISTEN_MADDR)
        return host


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


async def host_pair_factory() -> Tuple[BasicHost, BasicHost]:
    hosts = await asyncio.gather(
        *[HostFactory.create_and_listen(), HostFactory.create_and_listen()]
    )
    await connect(hosts[0], hosts[1])
    return hosts[0], hosts[1]


async def connection_pair_factory() -> Tuple[Mplex, BasicHost, Mplex, BasicHost]:
    host_0, host_1 = await host_pair_factory()
    mplex_conn_0 = host_0.get_network().connections[host_1.get_id()]
    mplex_conn_1 = host_1.get_network().connections[host_0.get_id()]
    return mplex_conn_0, host_0, mplex_conn_1, host_1


async def net_stream_pair_factory() -> Tuple[
    INetStream, BasicHost, INetStream, BasicHost
]:
    protocol_id = "/example/id/1"

    stream_1: INetStream

    # Just a proxy, we only care about the stream
    def handler(stream: INetStream) -> None:
        nonlocal stream_1
        stream_1 = stream

    host_0, host_1 = await host_pair_factory()
    host_1.set_stream_handler(protocol_id, handler)

    stream_0 = await host_0.new_stream(host_1.get_id(), [protocol_id])
    return stream_0, host_0, stream_1, host_1

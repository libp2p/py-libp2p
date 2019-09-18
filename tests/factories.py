import asyncio
from typing import Dict, Tuple

import factory

from libp2p import generate_new_rsa_identity, initialize_default_swarm
from libp2p.crypto.keys import KeyPair
from libp2p.host.basic_host import BasicHost
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.network.swarm import Swarm
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream
from libp2p.transport.typing import TMuxerOptions
from libp2p.typing import TProtocol
from tests.configs import LISTEN_MADDR
from tests.pubsub.configs import (
    FLOODSUB_PROTOCOL_ID,
    GOSSIPSUB_PARAMS,
    GOSSIPSUB_PROTOCOL_ID,
)
from tests.utils import connect, connect_swarm


def security_transport_factory(
    is_secure: bool, key_pair: KeyPair
) -> Dict[TProtocol, BaseSecureTransport]:
    if not is_secure:
        return {PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)}
    else:
        return {secio.ID: secio.Transport(key_pair)}


def SwarmFactory(is_secure: bool, muxer_opt: TMuxerOptions = None) -> Swarm:
    key_pair = generate_new_rsa_identity()
    sec_opt = security_transport_factory(is_secure, key_pair)
    return initialize_default_swarm(key_pair, sec_opt=sec_opt, muxer_opt=muxer_opt)


class ListeningSwarmFactory(factory.Factory):
    class Meta:
        model = Swarm

    @classmethod
    async def create_and_listen(
        cls, is_secure: bool, muxer_opt: TMuxerOptions = None
    ) -> Swarm:
        swarm = SwarmFactory(is_secure, muxer_opt=muxer_opt)
        await swarm.listen(LISTEN_MADDR)
        return swarm

    @classmethod
    async def create_batch_and_listen(
        cls, is_secure: bool, number: int, muxer_opt: TMuxerOptions = None
    ) -> Tuple[Swarm, ...]:
        return await asyncio.gather(
            *[
                cls.create_and_listen(is_secure, muxer_opt=muxer_opt)
                for _ in range(number)
            ]
        )


class HostFactory(factory.Factory):
    class Meta:
        model = BasicHost

    class Params:
        is_secure = False

    network = factory.LazyAttribute(lambda o: SwarmFactory(o.is_secure))

    @classmethod
    async def create_and_listen(cls, is_secure: bool) -> BasicHost:
        swarms = await ListeningSwarmFactory.create_batch_and_listen(is_secure, 1)
        return BasicHost(swarms[0])

    @classmethod
    async def create_batch_and_listen(
        cls, is_secure: bool, number: int
    ) -> Tuple[BasicHost, ...]:
        swarms = await ListeningSwarmFactory.create_batch_and_listen(is_secure, number)
        return tuple(BasicHost(swarm) for swarm in range(swarms))


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


async def swarm_pair_factory(
    is_secure: bool, muxer_opt: TMuxerOptions = None
) -> Tuple[Swarm, Swarm]:
    swarms = await ListeningSwarmFactory.create_batch_and_listen(
        is_secure, 2, muxer_opt=muxer_opt
    )
    await connect_swarm(swarms[0], swarms[1])
    return swarms[0], swarms[1]


async def host_pair_factory(is_secure) -> Tuple[BasicHost, BasicHost]:
    hosts = await asyncio.gather(
        *[
            HostFactory.create_and_listen(is_secure),
            HostFactory.create_and_listen(is_secure),
        ]
    )
    await connect(hosts[0], hosts[1])
    return hosts[0], hosts[1]


async def swarm_conn_pair_factory(
    is_secure: bool, muxer_opt: TMuxerOptions = None
) -> Tuple[SwarmConn, Swarm, SwarmConn, Swarm]:
    swarms = await swarm_pair_factory(is_secure)
    conn_0 = swarms[0].connections[swarms[1].get_peer_id()]
    conn_1 = swarms[1].connections[swarms[0].get_peer_id()]
    return conn_0, swarms[0], conn_1, swarms[1]


async def mplex_conn_pair_factory(is_secure: bool) -> Tuple[Mplex, Swarm, Mplex, Swarm]:
    muxer_opt = {MPLEX_PROTOCOL_ID: Mplex}
    conn_0, swarm_0, conn_1, swarm_1 = await swarm_conn_pair_factory(
        is_secure, muxer_opt=muxer_opt
    )
    return conn_0.conn, swarm_0, conn_1.conn, swarm_1


async def mplex_stream_pair_factory(
    is_secure: bool
) -> Tuple[MplexStream, Swarm, MplexStream, Swarm]:
    mplex_conn_0, swarm_0, mplex_conn_1, swarm_1 = await mplex_conn_pair_factory(
        is_secure
    )
    stream_0 = await mplex_conn_0.open_stream()
    await asyncio.sleep(0.01)
    stream_1: MplexStream
    async with mplex_conn_1.streams_lock:
        if len(mplex_conn_1.streams) != 1:
            raise Exception("Mplex should not have any stream upon connection")
        stream_1 = tuple(mplex_conn_1.streams.values())[0]
    return stream_0, swarm_0, stream_1, swarm_1


async def net_stream_pair_factory(
    is_secure: bool
) -> Tuple[INetStream, BasicHost, INetStream, BasicHost]:
    protocol_id = "/example/id/1"

    stream_1: INetStream

    # Just a proxy, we only care about the stream
    def handler(stream: INetStream) -> None:
        nonlocal stream_1
        stream_1 = stream

    host_0, host_1 = await host_pair_factory(is_secure)
    host_1.set_stream_handler(protocol_id, handler)

    stream_0 = await host_0.new_stream(host_1.get_id(), [protocol_id])
    return stream_0, host_0, stream_1, host_1

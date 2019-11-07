import asyncio
from typing import Dict, Tuple

import factory

from libp2p import generate_new_rsa_identity, generate_peer_id_from
from libp2p.crypto.keys import KeyPair
from libp2p.host.basic_host import BasicHost
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.network.swarm import Swarm
from libp2p.peer.peerstore import PeerStore
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.typing import TMuxerOptions
from libp2p.transport.upgrader import TransportUpgrader
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


class SwarmFactory(factory.Factory):
    class Meta:
        model = Swarm

    class Params:
        is_secure = False
        key_pair = factory.LazyFunction(generate_new_rsa_identity)
        muxer_opt = {MPLEX_PROTOCOL_ID: Mplex}

    peer_id = factory.LazyAttribute(lambda o: generate_peer_id_from(o.key_pair))
    peerstore = factory.LazyFunction(PeerStore)
    upgrader = factory.LazyAttribute(
        lambda o: TransportUpgrader(
            security_transport_factory(o.is_secure, o.key_pair), o.muxer_opt
        )
    )
    transport = factory.LazyFunction(TCP)

    @classmethod
    async def create_and_listen(
        cls, is_secure: bool, key_pair: KeyPair = None, muxer_opt: TMuxerOptions = None
    ) -> Swarm:
        # `factory.Factory.__init__` does *not* prepare a *default value* if we pass
        # an argument explicitly with `None`. If an argument is `None`, we don't pass it to
        # `factory.Factory.__init__`, in order to let the function initialize it.
        optional_kwargs = {}
        if key_pair is not None:
            optional_kwargs["key_pair"] = key_pair
        if muxer_opt is not None:
            optional_kwargs["muxer_opt"] = muxer_opt
        swarm = cls(is_secure=is_secure, **optional_kwargs)
        await swarm.listen(LISTEN_MADDR)
        return swarm

    @classmethod
    async def create_batch_and_listen(
        cls, is_secure: bool, number: int, muxer_opt: TMuxerOptions = None
    ) -> Tuple[Swarm, ...]:
        return await asyncio.gather(
            *[
                cls.create_and_listen(is_secure=is_secure, muxer_opt=muxer_opt)
                for _ in range(number)
            ]
        )


class HostFactory(factory.Factory):
    class Meta:
        model = BasicHost

    class Params:
        is_secure = False
        key_pair = factory.LazyFunction(generate_new_rsa_identity)

    public_key = factory.LazyAttribute(lambda o: o.key_pair.public_key)
    network = factory.LazyAttribute(
        lambda o: SwarmFactory(is_secure=o.is_secure, key_pair=o.key_pair)
    )

    @classmethod
    async def create_batch_and_listen(
        cls, is_secure: bool, number: int
    ) -> Tuple[BasicHost, ...]:
        key_pairs = [generate_new_rsa_identity() for _ in range(number)]
        swarms = await asyncio.gather(
            *[
                SwarmFactory.create_and_listen(is_secure, key_pair)
                for key_pair in key_pairs
            ]
        )
        return tuple(
            BasicHost(key_pair.public_key, swarm)
            for key_pair, swarm in zip(key_pairs, swarms)
        )


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
    swarms = await SwarmFactory.create_batch_and_listen(
        is_secure, 2, muxer_opt=muxer_opt
    )
    await connect_swarm(swarms[0], swarms[1])
    return swarms[0], swarms[1]


async def host_pair_factory(is_secure) -> Tuple[BasicHost, BasicHost]:
    hosts = await HostFactory.create_batch_and_listen(is_secure, 2)
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
    return conn_0.muxed_conn, swarm_0, conn_1.muxed_conn, swarm_1


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

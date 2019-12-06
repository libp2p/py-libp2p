from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator, Dict, Sequence, Tuple, cast

from async_service import background_trio_service
import factory
import trio

from libp2p import generate_new_rsa_identity, generate_peer_id_from
from libp2p.crypto.keys import KeyPair
from libp2p.host.basic_host import BasicHost
from libp2p.host.host_interface import IHost
from libp2p.io.abc import ReadWriteCloser
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.pubsub_router_interface import IPubsubRouter
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream
from libp2p.tools.constants import GOSSIPSUB_PARAMS
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.typing import TMuxerOptions
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.typing import TProtocol

from .constants import FLOODSUB_PROTOCOL_ID, GOSSIPSUB_PROTOCOL_ID, LISTEN_MADDR
from .utils import connect, connect_swarm


class IDFactory(factory.Factory):
    class Meta:
        model = ID

    peer_id_bytes = factory.LazyFunction(
        lambda: generate_peer_id_from(generate_new_rsa_identity())
    )


def security_transport_factory(
    is_secure: bool, key_pair: KeyPair
) -> Dict[TProtocol, BaseSecureTransport]:
    if not is_secure:
        return {PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)}
    else:
        return {secio.ID: secio.Transport(key_pair)}


@asynccontextmanager
async def raw_conn_factory(
    nursery: trio.Nursery
) -> AsyncIterator[Tuple[IRawConnection, IRawConnection]]:
    conn_0 = None
    conn_1 = None

    async def tcp_stream_handler(stream: ReadWriteCloser) -> None:
        nonlocal conn_1
        conn_1 = RawConnection(stream, initiator=False)
        await trio.sleep_forever()

    tcp_transport = TCP()
    listener = tcp_transport.create_listener(tcp_stream_handler)
    await listener.listen(LISTEN_MADDR, nursery)
    listening_maddr = listener.multiaddrs[0]
    conn_0 = await tcp_transport.dial(listening_maddr)
    print("raw_conn_factory")
    yield conn_0, conn_1


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
    @asynccontextmanager
    async def create_and_listen(
        cls, is_secure: bool, key_pair: KeyPair = None, muxer_opt: TMuxerOptions = None
    ) -> AsyncIterator[Swarm]:
        # `factory.Factory.__init__` does *not* prepare a *default value* if we pass
        # an argument explicitly with `None`. If an argument is `None`, we don't pass it to
        # `factory.Factory.__init__`, in order to let the function initialize it.
        optional_kwargs: Dict[str, Any] = {}
        if key_pair is not None:
            optional_kwargs["key_pair"] = key_pair
        if muxer_opt is not None:
            optional_kwargs["muxer_opt"] = muxer_opt
        swarm = cls(is_secure=is_secure, **optional_kwargs)
        async with background_trio_service(swarm):
            await swarm.listen(LISTEN_MADDR)
            yield swarm

    @classmethod
    @asynccontextmanager
    async def create_batch_and_listen(
        cls, is_secure: bool, number: int, muxer_opt: TMuxerOptions = None
    ) -> AsyncIterator[Tuple[Swarm, ...]]:
        async with AsyncExitStack() as stack:
            ctx_mgrs = [
                await stack.enter_async_context(
                    cls.create_and_listen(is_secure=is_secure, muxer_opt=muxer_opt)
                )
                for _ in range(number)
            ]
            yield tuple(ctx_mgrs)


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
    @asynccontextmanager
    async def create_batch_and_listen(
        cls, is_secure: bool, number: int
    ) -> AsyncIterator[Tuple[BasicHost, ...]]:
        key_pairs = [generate_new_rsa_identity() for _ in range(number)]
        async with AsyncExitStack() as stack:
            swarms = [
                await stack.enter_async_context(
                    SwarmFactory.create_and_listen(is_secure, key_pair)
                )
                for key_pair in key_pairs
            ]
            hosts = tuple(
                BasicHost(key_pair.public_key, swarm)
                for key_pair, swarm in zip(key_pairs, swarms)
            )
            yield hosts


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
    cache_size = None

    @classmethod
    @asynccontextmanager
    async def create_and_start(
        cls, host: IHost, router: IPubsubRouter, cache_size: int
    ) -> AsyncIterator[Pubsub]:
        pubsub = PubsubFactory(host=host, router=router, cache_size=cache_size)
        async with background_trio_service(pubsub):
            yield pubsub

    @classmethod
    @asynccontextmanager
    async def _create_batch_with_router(
        cls,
        number: int,
        routers: Sequence[IPubsubRouter],
        is_secure: bool = False,
        cache_size: int = None,
    ) -> AsyncIterator[Tuple[Pubsub, ...]]:
        async with HostFactory.create_batch_and_listen(is_secure, number) as hosts:
            # Pubsubs should exit before hosts
            async with AsyncExitStack() as stack:
                pubsubs = [
                    await stack.enter_async_context(
                        cls.create_and_start(host, router, cache_size)
                    )
                    for host, router in zip(hosts, routers)
                ]
                yield tuple(pubsubs)

    @classmethod
    @asynccontextmanager
    async def create_batch_with_floodsub(
        cls,
        number: int,
        is_secure: bool = False,
        cache_size: int = None,
        protocols: Sequence[TProtocol] = None,
    ) -> AsyncIterator[Tuple[Pubsub, ...]]:
        if protocols is not None:
            floodsubs = FloodsubFactory.create_batch(number, protocols=list(protocols))
        else:
            floodsubs = FloodsubFactory.create_batch(number)
        async with cls._create_batch_with_router(
            number, floodsubs, is_secure, cache_size
        ) as pubsubs:
            yield pubsubs

    @classmethod
    @asynccontextmanager
    async def create_batch_with_gossipsub(
        cls,
        number: int,
        *,
        is_secure: bool = False,
        cache_size: int = None,
        protocols: Sequence[TProtocol] = None,
        degree: int = GOSSIPSUB_PARAMS.degree,
        degree_low: int = GOSSIPSUB_PARAMS.degree_low,
        degree_high: int = GOSSIPSUB_PARAMS.degree_high,
        time_to_live: int = GOSSIPSUB_PARAMS.time_to_live,
        gossip_window: int = GOSSIPSUB_PARAMS.gossip_window,
        gossip_history: int = GOSSIPSUB_PARAMS.gossip_history,
        heartbeat_interval: float = GOSSIPSUB_PARAMS.heartbeat_interval,
    ) -> AsyncIterator[Tuple[Pubsub, ...]]:
        if protocols is not None:
            gossipsubs = GossipsubFactory.create_batch(
                number,
                protocols=protocols,
                degree=degree,
                degree_low=degree_low,
                degree_high=degree_high,
                time_to_live=time_to_live,
                gossip_window=gossip_window,
                heartbeat_interval=heartbeat_interval,
            )
        else:
            gossipsubs = GossipsubFactory.create_batch(
                number,
                degree=degree,
                degree_low=degree_low,
                degree_high=degree_high,
                time_to_live=time_to_live,
                gossip_window=gossip_window,
                heartbeat_interval=heartbeat_interval,
            )

        async with cls._create_batch_with_router(
            number, gossipsubs, is_secure, cache_size
        ) as pubsubs:
            async with AsyncExitStack() as stack:
                for router in gossipsubs:
                    await stack.enter_async_context(background_trio_service(router))
                yield pubsubs


@asynccontextmanager
async def swarm_pair_factory(
    is_secure: bool, muxer_opt: TMuxerOptions = None
) -> AsyncIterator[Tuple[Swarm, Swarm]]:
    async with SwarmFactory.create_batch_and_listen(
        is_secure, 2, muxer_opt=muxer_opt
    ) as swarms:
        await connect_swarm(swarms[0], swarms[1])
        yield swarms[0], swarms[1]


@asynccontextmanager
async def host_pair_factory(
    is_secure: bool
) -> AsyncIterator[Tuple[BasicHost, BasicHost]]:
    async with HostFactory.create_batch_and_listen(is_secure, 2) as hosts:
        await connect(hosts[0], hosts[1])
        yield hosts[0], hosts[1]


@asynccontextmanager
async def swarm_conn_pair_factory(
    is_secure: bool, muxer_opt: TMuxerOptions = None
) -> AsyncIterator[Tuple[SwarmConn, SwarmConn]]:
    async with swarm_pair_factory(is_secure) as swarms:
        conn_0 = swarms[0].connections[swarms[1].get_peer_id()]
        conn_1 = swarms[1].connections[swarms[0].get_peer_id()]
        yield cast(SwarmConn, conn_0), cast(SwarmConn, conn_1)


@asynccontextmanager
async def mplex_conn_pair_factory(
    is_secure: bool
) -> AsyncIterator[Tuple[Mplex, Mplex]]:
    muxer_opt = {MPLEX_PROTOCOL_ID: Mplex}
    async with swarm_conn_pair_factory(is_secure, muxer_opt=muxer_opt) as swarm_pair:
        yield (
            cast(Mplex, swarm_pair[0].muxed_conn),
            cast(Mplex, swarm_pair[1].muxed_conn),
        )


@asynccontextmanager
async def mplex_stream_pair_factory(
    is_secure: bool
) -> AsyncIterator[Tuple[MplexStream, MplexStream]]:
    async with mplex_conn_pair_factory(is_secure) as mplex_conn_pair_info:
        mplex_conn_0, mplex_conn_1 = mplex_conn_pair_info
        stream_0 = cast(MplexStream, await mplex_conn_0.open_stream())
        await trio.sleep(0.01)
        stream_1: MplexStream
        async with mplex_conn_1.streams_lock:
            if len(mplex_conn_1.streams) != 1:
                raise Exception("Mplex should not have any other stream")
            stream_1 = tuple(mplex_conn_1.streams.values())[0]
        yield stream_0, stream_1


@asynccontextmanager
async def net_stream_pair_factory(
    is_secure: bool
) -> AsyncIterator[Tuple[INetStream, INetStream]]:
    protocol_id = TProtocol("/example/id/1")

    stream_1: INetStream

    # Just a proxy, we only care about the stream
    def handler(stream: INetStream) -> None:
        nonlocal stream_1
        stream_1 = stream

    async with host_pair_factory(is_secure) as hosts:
        hosts[1].set_stream_handler(protocol_id, handler)

        stream_0 = await hosts[0].new_stream(hosts[1].get_id(), [protocol_id])
        yield stream_0, stream_1

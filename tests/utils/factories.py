from collections.abc import (
    AsyncIterator,
    Callable,
    Sequence,
)
from contextlib import (
    AsyncExitStack,
    asynccontextmanager,
)
from typing import (
    Any,
    cast,
)

import factory
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p import (
    generate_new_rsa_identity,
    generate_peer_id_from,
)
from libp2p.abc import (
    IHost,
    INetStream,
    IPeerRouting,
    IPubsubRouter,
    IRawConnection,
    ISecureConn,
    ISecureTransport,
)
from libp2p.crypto.ed25519 import create_new_key_pair as create_ed25519_key_pair
from libp2p.crypto.keys import (
    KeyPair,
    PrivateKey,
)
from libp2p.crypto.secp256k1 import create_new_key_pair as create_secp256k1_key_pair
from libp2p.custom_types import (
    TMuxerOptions,
    TProtocol,
    TSecurityOptions,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.host.routed_host import (
    RoutedHost,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.network.connection.swarm_connection import (
    SwarmConn,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import (
    PeerStore,
)
from libp2p.pubsub.floodsub import (
    FloodSub,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
import libp2p.pubsub.pb.rpc_pb2 as rpc_pb2
from libp2p.pubsub.pubsub import (
    Pubsub,
    get_peer_and_seqno_msg_id,
)
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.security.noise.messages import (
    NoiseHandshakePayload,
    make_handshake_payload_sig,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.stream_muxer.mplex.mplex_stream import (
    MplexStream,
)
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
    YamuxStream,
)
from libp2p.tools.async_service import (
    background_trio_service,
)
from libp2p.tools.constants import (
    FLOODSUB_PROTOCOL_ID,
    GOSSIPSUB_PARAMS,
    GOSSIPSUB_PROTOCOL_ID,
    LISTEN_MADDR,
)
from libp2p.tools.utils import (
    connect,
    connect_swarm,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)

DEFAULT_SECURITY_PROTOCOL_ID = PLAINTEXT_PROTOCOL_ID


def default_key_pair_factory() -> KeyPair:
    return generate_new_rsa_identity()


class IDFactory(factory.Factory):
    class Meta:
        model = ID

    peer_id_bytes = factory.LazyFunction(
        lambda: generate_peer_id_from(default_key_pair_factory()).to_bytes()
    )


def initialize_peerstore_with_our_keypair(self_id: ID, key_pair: KeyPair) -> PeerStore:
    peer_store = PeerStore()
    peer_store.add_key_pair(self_id, key_pair)
    return peer_store


def noise_static_key_factory() -> PrivateKey:
    return create_ed25519_key_pair().private_key


def noise_handshake_payload_factory() -> NoiseHandshakePayload:
    libp2p_keypair = create_secp256k1_key_pair()
    noise_static_privkey = noise_static_key_factory()
    return NoiseHandshakePayload(
        libp2p_keypair.public_key,
        make_handshake_payload_sig(
            libp2p_keypair.private_key, noise_static_privkey.get_public_key()
        ),
    )


def plaintext_transport_factory(key_pair: KeyPair, peerstore=None) -> ISecureTransport:
    return InsecureTransport(key_pair, peerstore=peerstore)


def secio_transport_factory(key_pair: KeyPair) -> ISecureTransport:
    return secio.Transport(key_pair)


def noise_transport_factory(key_pair: KeyPair) -> ISecureTransport:
    return NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=noise_static_key_factory(),
        early_data=None,
        with_noise_pipes=False,
    )


def security_options_factory_factory(
    protocol_id: TProtocol | None = None,
) -> Callable[[KeyPair], TSecurityOptions]:
    if protocol_id is None:
        protocol_id = DEFAULT_SECURITY_PROTOCOL_ID

    def security_options_factory(key_pair: KeyPair) -> TSecurityOptions:
        transport_factory: Callable[[KeyPair], ISecureTransport]
        if protocol_id == PLAINTEXT_PROTOCOL_ID:
            transport_factory = plaintext_transport_factory
        elif protocol_id == secio.ID:
            transport_factory = secio_transport_factory
        elif protocol_id == NOISE_PROTOCOL_ID:
            transport_factory = noise_transport_factory
        else:
            raise Exception(f"security transport {protocol_id} is not supported")
        return {protocol_id: transport_factory(key_pair)}

    return security_options_factory


def mplex_transport_factory() -> TMuxerOptions:
    return {MPLEX_PROTOCOL_ID: Mplex}


def default_mplex_muxer_transport_factory() -> TMuxerOptions:
    return mplex_transport_factory()


def yamux_transport_factory() -> TMuxerOptions:
    return {cast(TProtocol, "/yamux/1.0.0"): Yamux}


def default_muxer_transport_factory() -> TMuxerOptions:
    return yamux_transport_factory()


@asynccontextmanager
async def raw_conn_factory(
    nursery: trio.Nursery,
) -> AsyncIterator[tuple[IRawConnection, IRawConnection]]:
    conn_0: IRawConnection | None = None
    conn_1: IRawConnection | None = None
    event = trio.Event()

    async def tcp_stream_handler(stream: ReadWriteCloser) -> None:
        nonlocal conn_1
        conn_1 = RawConnection(stream, initiator=False)
        event.set()
        await trio.sleep_forever()

    tcp_transport = TCP()
    listener = tcp_transport.create_listener(tcp_stream_handler)
    await listener.listen(LISTEN_MADDR, nursery)
    listening_maddr = listener.get_addrs()[0]
    conn_0 = await tcp_transport.dial(listening_maddr)
    await event.wait()
    assert conn_0 is not None and conn_1 is not None
    yield conn_0, conn_1


@asynccontextmanager
async def noise_conn_factory(
    nursery: trio.Nursery,
) -> AsyncIterator[tuple[ISecureConn, ISecureConn]]:
    local_transport = cast(
        NoiseTransport, noise_transport_factory(create_secp256k1_key_pair())
    )
    remote_transport = cast(
        NoiseTransport, noise_transport_factory(create_secp256k1_key_pair())
    )

    local_secure_conn: ISecureConn | None = None
    remote_secure_conn: ISecureConn | None = None

    async def upgrade_local_conn() -> None:
        nonlocal local_secure_conn
        local_secure_conn = await local_transport.secure_outbound(
            local_conn, remote_transport.local_peer
        )

    async def upgrade_remote_conn() -> None:
        nonlocal remote_secure_conn
        remote_secure_conn = await remote_transport.secure_inbound(remote_conn)

    async with raw_conn_factory(nursery) as conns:
        local_conn, remote_conn = conns
        async with trio.open_nursery() as nursery:
            nursery.start_soon(upgrade_local_conn)
            nursery.start_soon(upgrade_remote_conn)
        if local_secure_conn is None or remote_secure_conn is None:
            raise Exception(
                "local or remote secure conn has not been successfully upgraded"
                f"local_secure_conn={local_secure_conn}, "
                f"remote_secure_conn={remote_secure_conn}"
            )
        yield local_secure_conn, remote_secure_conn


class SwarmFactory(factory.Factory):
    class Meta:
        model = Swarm

    class Params:
        key_pair = factory.LazyFunction(default_key_pair_factory)
        security_protocol = DEFAULT_SECURITY_PROTOCOL_ID
        muxer_opt = factory.LazyFunction(default_muxer_transport_factory)

    peer_id = factory.LazyAttribute(lambda o: generate_peer_id_from(o.key_pair))
    peerstore = factory.LazyAttribute(
        lambda o: initialize_peerstore_with_our_keypair(o.peer_id, o.key_pair)
    )
    upgrader = factory.LazyAttribute(
        lambda o: TransportUpgrader(
            (security_options_factory_factory(o.security_protocol))(o.key_pair),
            o.muxer_opt,
        )
    )
    transport = factory.LazyFunction(TCP)

    @classmethod
    @asynccontextmanager
    async def create_and_listen(
        cls,
        key_pair: KeyPair | None = None,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
    ) -> AsyncIterator[Swarm]:
        # `factory.Factory.__init__` does *not* prepare a *default value* if we pass
        # an argument explicitly with `None`. If an argument is `None`, we don't pass it
        # to `factory.Factory.__init__`, in order to let the function initialize it.
        optional_kwargs: dict[str, Any] = {}
        if key_pair is not None:
            optional_kwargs["key_pair"] = key_pair
        if security_protocol is not None:
            optional_kwargs["security_protocol"] = security_protocol
        if muxer_opt is not None:
            optional_kwargs["muxer_opt"] = muxer_opt
        swarm = cls(**optional_kwargs)
        async with background_trio_service(swarm):
            await swarm.listen(LISTEN_MADDR)
            yield swarm

    @classmethod
    @asynccontextmanager
    async def create_batch_and_listen(
        cls,
        number: int,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
    ) -> AsyncIterator[tuple[Swarm, ...]]:
        async with AsyncExitStack() as stack:
            ctx_mgrs = [
                await stack.enter_async_context(
                    cls.create_and_listen(
                        security_protocol=security_protocol, muxer_opt=muxer_opt
                    )
                )
                for _ in range(number)
            ]
            yield tuple(ctx_mgrs)


class HostFactory(factory.Factory):
    class Meta:
        model = BasicHost

    class Params:
        key_pair = factory.LazyFunction(default_key_pair_factory)
        security_protocol: TProtocol | None = None
        muxer_opt = factory.LazyFunction(default_muxer_transport_factory)

    network = factory.LazyAttribute(
        lambda o: SwarmFactory.build(
            security_protocol=o.security_protocol, muxer_opt=o.muxer_opt
        )
    )

    @classmethod
    @asynccontextmanager
    async def create_batch_and_listen(
        cls,
        number: int,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
    ) -> AsyncIterator[tuple[BasicHost, ...]]:
        async with SwarmFactory.create_batch_and_listen(
            number, security_protocol=security_protocol, muxer_opt=muxer_opt
        ) as swarms:
            hosts = tuple(BasicHost(swarm) for swarm in swarms)
            yield hosts


class DummyRouter(IPeerRouting):
    _routing_table: dict[ID, PeerInfo]

    def __init__(self) -> None:
        self._routing_table = dict()

    def _add_peer(self, peer_id: ID, addrs: list[Multiaddr]) -> None:
        self._routing_table[peer_id] = PeerInfo(peer_id, addrs)

    async def find_peer(self, peer_id: ID) -> PeerInfo | None:
        await trio.lowlevel.checkpoint()
        return self._routing_table.get(peer_id, None)


class RoutedHostFactory(factory.Factory):
    class Meta:
        model = RoutedHost

    class Params:
        key_pair = factory.LazyFunction(default_key_pair_factory)
        security_protocol: TProtocol | None = None
        muxer_opt = factory.LazyFunction(default_muxer_transport_factory)

    network = factory.LazyAttribute(
        lambda o: HostFactory.build(
            security_protocol=o.security_protocol, muxer_opt=o.muxer_opt
        ).get_network()
    )
    router = factory.LazyFunction(DummyRouter)

    @classmethod
    @asynccontextmanager
    async def create_batch_and_listen(
        cls,
        number: int,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
    ) -> AsyncIterator[tuple[RoutedHost, ...]]:
        routing_table = DummyRouter()
        async with HostFactory.create_batch_and_listen(
            number, security_protocol=security_protocol, muxer_opt=muxer_opt
        ) as hosts:
            for host in hosts:
                routing_table._add_peer(host.get_id(), host.get_addrs())
            routed_hosts = tuple(
                RoutedHost(host.get_network(), routing_table) for host in hosts
            )
            yield routed_hosts


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
    direct_peers = GOSSIPSUB_PARAMS.direct_peers
    gossip_window = GOSSIPSUB_PARAMS.gossip_window
    gossip_history = GOSSIPSUB_PARAMS.gossip_history
    heartbeat_initial_delay = GOSSIPSUB_PARAMS.heartbeat_initial_delay
    heartbeat_interval = GOSSIPSUB_PARAMS.heartbeat_interval
    direct_connect_initial_delay = GOSSIPSUB_PARAMS.direct_connect_initial_delay
    direct_connect_interval = GOSSIPSUB_PARAMS.direct_connect_interval
    do_px = GOSSIPSUB_PARAMS.do_px
    px_peers_count = GOSSIPSUB_PARAMS.px_peers_count
    prune_back_off = GOSSIPSUB_PARAMS.prune_back_off
    unsubscribe_back_off = GOSSIPSUB_PARAMS.unsubscribe_back_off


class PubsubFactory(factory.Factory):
    class Meta:
        model = Pubsub

    host = factory.SubFactory(HostFactory)
    router: IPubsubRouter | None = None
    cache_size: int | None = None
    strict_signing = False

    @classmethod
    @asynccontextmanager
    async def create_and_start(
        cls,
        host: IHost,
        router: IPubsubRouter,
        cache_size: int | None,
        seen_ttl: int,
        sweep_interval: int,
        strict_signing: bool,
        msg_id_constructor: Callable[[rpc_pb2.Message], bytes] | None = None,
    ) -> AsyncIterator[Pubsub]:
        if msg_id_constructor is None:
            msg_id_constructor = get_peer_and_seqno_msg_id
        pubsub = Pubsub(
            host=host,
            router=router,
            cache_size=cache_size,
            seen_ttl=seen_ttl,
            sweep_interval=sweep_interval,
            strict_signing=strict_signing,
            msg_id_constructor=msg_id_constructor,
        )
        async with background_trio_service(pubsub):
            await pubsub.wait_until_ready()
            yield pubsub

    @classmethod
    @asynccontextmanager
    async def _create_batch_with_router(
        cls,
        number: int,
        routers: Sequence[IPubsubRouter],
        cache_size: int | None = None,
        seen_ttl: int = 120,
        sweep_interval: int = 60,
        strict_signing: bool = False,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
        msg_id_constructor: Callable[[rpc_pb2.Message], bytes] | None = None,
    ) -> AsyncIterator[tuple[Pubsub, ...]]:
        async with HostFactory.create_batch_and_listen(
            number, security_protocol=security_protocol, muxer_opt=muxer_opt
        ) as hosts:
            # Pubsubs should exit before hosts
            async with AsyncExitStack() as stack:
                pubsubs = [
                    await stack.enter_async_context(
                        cls.create_and_start(
                            host,
                            router,
                            cache_size,
                            seen_ttl,
                            sweep_interval,
                            strict_signing,
                            msg_id_constructor,
                        )
                    )
                    for host, router in zip(hosts, routers)
                ]
                yield tuple(pubsubs)

    @classmethod
    @asynccontextmanager
    async def create_batch_with_floodsub(
        cls,
        number: int,
        cache_size: int | None = None,
        seen_ttl: int = 120,
        sweep_interval: int = 60,
        strict_signing: bool = False,
        protocols: Sequence[TProtocol] | None = None,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
        msg_id_constructor: None
        | (Callable[[rpc_pb2.Message], bytes]) = get_peer_and_seqno_msg_id,
    ) -> AsyncIterator[tuple[Pubsub, ...]]:
        if protocols is not None:
            floodsubs = FloodsubFactory.create_batch(number, protocols=list(protocols))
        else:
            floodsubs = FloodsubFactory.create_batch(number)
        async with cls._create_batch_with_router(
            number,
            floodsubs,
            cache_size,
            seen_ttl,
            sweep_interval,
            strict_signing,
            security_protocol=security_protocol,
            muxer_opt=muxer_opt,
            msg_id_constructor=msg_id_constructor,
        ) as pubsubs:
            yield pubsubs

    @classmethod
    @asynccontextmanager
    async def create_batch_with_gossipsub(
        cls,
        number: int,
        *,
        cache_size: int | None = None,
        strict_signing: bool = False,
        protocols: Sequence[TProtocol] | None = None,
        degree: int = GOSSIPSUB_PARAMS.degree,
        degree_low: int = GOSSIPSUB_PARAMS.degree_low,
        degree_high: int = GOSSIPSUB_PARAMS.degree_high,
        direct_peers: Sequence[PeerInfo] = GOSSIPSUB_PARAMS.direct_peers,
        time_to_live: int = GOSSIPSUB_PARAMS.time_to_live,
        gossip_window: int = GOSSIPSUB_PARAMS.gossip_window,
        gossip_history: int = GOSSIPSUB_PARAMS.gossip_history,
        heartbeat_interval: float = GOSSIPSUB_PARAMS.heartbeat_interval,
        heartbeat_initial_delay: float = GOSSIPSUB_PARAMS.heartbeat_initial_delay,
        direct_connect_initial_delay: float = GOSSIPSUB_PARAMS.direct_connect_initial_delay,  # noqa: E501
        direct_connect_interval: int = GOSSIPSUB_PARAMS.direct_connect_interval,
        do_px: bool = GOSSIPSUB_PARAMS.do_px,
        px_peers_count: int = GOSSIPSUB_PARAMS.px_peers_count,
        prune_back_off: int = GOSSIPSUB_PARAMS.prune_back_off,
        unsubscribe_back_off: int = GOSSIPSUB_PARAMS.unsubscribe_back_off,
        security_protocol: TProtocol | None = None,
        muxer_opt: TMuxerOptions | None = None,
        msg_id_constructor: None
        | (Callable[[rpc_pb2.Message], bytes]) = get_peer_and_seqno_msg_id,
    ) -> AsyncIterator[tuple[Pubsub, ...]]:
        if protocols is not None:
            gossipsubs = GossipsubFactory.create_batch(
                number,
                protocols=protocols,
                degree=degree,
                degree_low=degree_low,
                degree_high=degree_high,
                direct_peers=direct_peers,
                time_to_live=time_to_live,
                gossip_window=gossip_window,
                gossip_history=gossip_history,
                heartbeat_initial_delay=heartbeat_initial_delay,
                heartbeat_interval=heartbeat_interval,
                direct_connect_initial_delay=direct_connect_initial_delay,
                direct_connect_interval=direct_connect_interval,
                do_px=do_px,
                px_peers_count=px_peers_count,
                prune_back_off=prune_back_off,
                unsubscribe_back_off=unsubscribe_back_off,
            )
        else:
            gossipsubs = GossipsubFactory.create_batch(
                number,
                degree=degree,
                degree_low=degree_low,
                degree_high=degree_high,
                direct_peers=direct_peers,
                time_to_live=time_to_live,
                gossip_window=gossip_window,
                heartbeat_interval=heartbeat_interval,
                heartbeat_initial_delay=heartbeat_initial_delay,
                direct_connect_initial_delay=direct_connect_initial_delay,
                direct_connect_interval=direct_connect_interval,
                do_px=do_px,
                px_peers_count=px_peers_count,
                prune_back_off=prune_back_off,
                unsubscribe_back_off=unsubscribe_back_off,
            )

        async with cls._create_batch_with_router(
            number,
            gossipsubs,
            cache_size,
            120,  # seen_ttl
            60,  # sweep_interval
            strict_signing,
            security_protocol=security_protocol,
            muxer_opt=muxer_opt,
            msg_id_constructor=msg_id_constructor,
        ) as pubsubs:
            async with AsyncExitStack() as stack:
                for router in gossipsubs:
                    await stack.enter_async_context(background_trio_service(router))
                yield pubsubs


@asynccontextmanager
async def swarm_pair_factory(
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIterator[tuple[Swarm, Swarm]]:
    async with SwarmFactory.create_batch_and_listen(
        2, security_protocol=security_protocol, muxer_opt=muxer_opt
    ) as swarms:
        await connect_swarm(swarms[0], swarms[1])
        yield swarms[0], swarms[1]


@asynccontextmanager
async def host_pair_factory(
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIterator[tuple[BasicHost, BasicHost]]:
    async with HostFactory.create_batch_and_listen(
        2, security_protocol=security_protocol, muxer_opt=muxer_opt
    ) as hosts:
        await connect(hosts[0], hosts[1])
        yield hosts[0], hosts[1]


@asynccontextmanager
async def swarm_conn_pair_factory(
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIterator[tuple[SwarmConn, SwarmConn]]:
    async with swarm_pair_factory(
        security_protocol=security_protocol, muxer_opt=muxer_opt
    ) as swarms:
        conn_0 = swarms[0].connections[swarms[1].get_peer_id()]
        conn_1 = swarms[1].connections[swarms[0].get_peer_id()]
        yield cast(SwarmConn, conn_0), cast(SwarmConn, conn_1)


@asynccontextmanager
async def mplex_conn_pair_factory(
    security_protocol: TProtocol | None = None,
) -> AsyncIterator[tuple[Mplex, Mplex]]:
    async with swarm_conn_pair_factory(
        security_protocol=security_protocol,
        muxer_opt=default_mplex_muxer_transport_factory(),
    ) as swarm_pair:
        yield (
            cast(Mplex, swarm_pair[0].muxed_conn),
            cast(Mplex, swarm_pair[1].muxed_conn),
        )


@asynccontextmanager
async def mplex_stream_pair_factory(
    security_protocol: TProtocol | None = None,
) -> AsyncIterator[tuple[MplexStream, MplexStream]]:
    async with mplex_conn_pair_factory(
        security_protocol=security_protocol
    ) as mplex_conn_pair_info:
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
async def yamux_conn_pair_factory(
    security_protocol: TProtocol | None = None,
) -> AsyncIterator[tuple[Yamux, Yamux]]:
    async with swarm_conn_pair_factory(
        security_protocol=security_protocol, muxer_opt=default_muxer_transport_factory()
    ) as swarm_pair:
        yield (
            cast(Yamux, swarm_pair[0].muxed_conn),
            cast(Yamux, swarm_pair[1].muxed_conn),
        )


@asynccontextmanager
async def yamux_stream_pair_factory(
    security_protocol: TProtocol | None = None,
) -> AsyncIterator[tuple[YamuxStream, YamuxStream]]:
    async with yamux_conn_pair_factory(
        security_protocol=security_protocol
    ) as yamux_conn_pair_info:
        yamux_conn_0, yamux_conn_1 = yamux_conn_pair_info
        stream_0 = await yamux_conn_0.open_stream()
        await trio.sleep(0.01)
        stream_1: YamuxStream
        async with yamux_conn_1.streams_lock:
            if len(yamux_conn_1.streams) != 1:
                raise Exception("Yamux should not have any other stream")
            stream_1 = tuple(yamux_conn_1.streams.values())[0]
        yield stream_0, stream_1


@asynccontextmanager
async def net_stream_pair_factory(
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIterator[tuple[INetStream, INetStream]]:
    protocol_id = TProtocol("/example/id/1")

    stream_1: INetStream | None = None

    # Just a proxy, we only care about the stream.
    # Add a barrier to avoid stream being removed.
    event_handler_finished = trio.Event()

    async def handler(stream: INetStream) -> None:
        nonlocal stream_1
        stream_1 = stream
        await event_handler_finished.wait()

    async with host_pair_factory(
        security_protocol=security_protocol, muxer_opt=muxer_opt
    ) as hosts:
        hosts[1].set_stream_handler(protocol_id, handler)

        stream_0 = await hosts[0].new_stream(hosts[1].get_id(), [protocol_id])
        assert stream_1 is not None
        yield stream_0, stream_1
        event_handler_finished.set()

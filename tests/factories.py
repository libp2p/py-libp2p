from collections.abc import (
    Sequence,
)
from collections.abc import AsyncIterator as AsyncIteratorABC
from contextlib import (
    AsyncExitStack,
    asynccontextmanager,
)
from typing import (
    Any,
    Callable,
    cast,
)

import anyio
import factory
from multiaddr import (
    Multiaddr,
)

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
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.security.noise.transport import Transport as NoiseTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.stream_muxer.mplex.mplex_stream import (
    MplexStream,
)
from libp2p.tools.anyio_service import (
    AnyIOManager,
    background_anyio_service,
)
from libp2p.tools.anyio_service.abc import (
    ServiceAPI,
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


class IDFactory(factory.Factory[ID]):
    class Meta:
        model = ID

    peer_id_bytes = factory.LazyFunction(
        lambda: generate_peer_id_from(default_key_pair_factory())
    )  # type: ignore


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


def plaintext_transport_factory(key_pair: KeyPair) -> ISecureTransport:
    return InsecureTransport(key_pair)


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


def default_muxer_transport_factory() -> TMuxerOptions:
    return mplex_transport_factory()


@asynccontextmanager
async def raw_conn_factory() -> AsyncIteratorABC[tuple[IRawConnection, IRawConnection]]:
    conn_0: IRawConnection | None = None
    conn_1: IRawConnection | None = None
    event = anyio.Event()

    async def tcp_stream_handler(stream: ReadWriteCloser) -> None:
        nonlocal conn_1
        conn_1 = RawConnection(stream, initiator=False)
        event.set()
        await anyio.sleep_forever()

    tcp_transport = TCP()
    listener = tcp_transport.create_listener(tcp_stream_handler)
    # AnyIO doesn’t require nursery
    await listener.listen(LISTEN_MADDR)  # type: ignore[call-arg]
    listening_maddr = listener.get_addrs()[0]
    conn_0 = await tcp_transport.dial(listening_maddr)
    await event.wait()
    if conn_0 is None or conn_1 is None:
        raise ValueError("Connections not established")
    yield conn_0, conn_1


@asynccontextmanager
async def noise_conn_factory() -> AsyncIteratorABC[tuple[ISecureConn, ISecureConn]]:
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

    async with raw_conn_factory() as conns:
        local_conn, remote_conn = conns
        async with anyio.create_task_group() as tg:
            tg.start_soon(upgrade_local_conn)
            tg.start_soon(upgrade_remote_conn)
            await anyio.sleep(0.1)
        if local_secure_conn is None or remote_secure_conn is None:
            raise Exception(
                f"Failed to upgrade:"
                f"local={local_secure_conn}, remote={remote_secure_conn}"
            )
        yield local_secure_conn, remote_secure_conn


class SwarmService(ServiceAPI):
    def __init__(
        self,
        key_pair: KeyPair,
        security_protocol: TProtocol,
        muxer_opt: TMuxerOptions,
    ) -> None:
        self.peer_id = generate_peer_id_from(key_pair)
        self.peerstore = initialize_peerstore_with_our_keypair(self.peer_id, key_pair)
        self.upgrader = TransportUpgrader(
            security_options_factory_factory(security_protocol)(key_pair),
            muxer_opt,
        )
        self.transport = TCP()
        self.swarm = Swarm(self.peer_id, self.peerstore, self.upgrader, self.transport)
        self.manager: AnyIOManager | None = None

    async def run(self) -> None:
        while self.manager and self.manager.is_running:
            await anyio.sleep(0.1)

    def get_manager(self) -> AnyIOManager | None:
        return self.manager


class SwarmFactory(factory.Factory[Swarm]):
    class Meta:
        model = Swarm

    @classmethod
    def _create(cls, model_class: type[Swarm], **kwargs: Any) -> Swarm:
        key_pair = kwargs.get("key_pair", default_key_pair_factory())
        security_protocol = kwargs.get(
            "security_protocol", DEFAULT_SECURITY_PROTOCOL_ID
        )
        muxer_opt = kwargs.get("muxer_opt", default_muxer_transport_factory())
        service = SwarmService(key_pair, security_protocol, muxer_opt)
        return service.swarm


class HostFactory(factory.Factory[BasicHost]):
    class Meta:
        model = BasicHost

    @classmethod
    def _create(cls, model_class: type[BasicHost], **kwargs: Any) -> BasicHost:
        key_pair = kwargs.get("key_pair", default_key_pair_factory())
        security_protocol = kwargs.get(
            "security_protocol", DEFAULT_SECURITY_PROTOCOL_ID
        )
        muxer_opt = kwargs.get("muxer_opt", default_muxer_transport_factory())
        swarm = SwarmFactory._create(
            Swarm,
            key_pair=key_pair,
            security_protocol=security_protocol,
            muxer_opt=muxer_opt,
        )
        return BasicHost(swarm)


class DummyRouter(IPeerRouting):
    _routing_table: dict[ID, PeerInfo]

    def __init__(self) -> None:
        self._routing_table = dict()

    def _add_peer(self, peer_id: ID, addrs: list[Multiaddr]) -> None:
        self._routing_table[peer_id] = PeerInfo(peer_id, addrs)

    async def find_peer(self, peer_id: ID) -> PeerInfo | None:
        await anyio.sleep(0)
        return self._routing_table.get(peer_id)


class RoutedHostFactory(factory.Factory[RoutedHost]):
    class Meta:
        model = RoutedHost

    @classmethod
    def _create(cls, model_class: type[RoutedHost], **kwargs: Any) -> RoutedHost:
        key_pair = kwargs.get("key_pair", default_key_pair_factory())
        security_protocol = kwargs.get(
            "security_protocol", DEFAULT_SECURITY_PROTOCOL_ID
        )
        muxer_opt = kwargs.get("muxer_opt", default_muxer_transport_factory())
        host = HostFactory._create(
            BasicHost,
            key_pair=key_pair,
            security_protocol=security_protocol,
            muxer_opt=muxer_opt,
        )
        router = DummyRouter()
        return RoutedHost(host.get_network(), router)


class FloodsubFactory(factory.Factory[FloodSub]):
    class Meta:
        model = FloodSub

    protocols = (FLOODSUB_PROTOCOL_ID,)


class GossipsubFactory(factory.Factory[GossipSub]):
    class Meta:
        model = GossipSub

    protocols = (GOSSIPSUB_PROTOCOL_ID,)
    degree = GOSSIPSUB_PARAMS.degree
    degree_low = GOSSIPSUB_PARAMS.degree_low
    degree_high = GOSSIPSUB_PARAMS.degree_high
    gossip_window = GOSSIPSUB_PARAMS.gossip_window
    gossip_history = GOSSIPSUB_PARAMS.gossip_history
    heartbeat_initial_delay = GOSSIPSUB_PARAMS.heartbeat_initial_delay
    heartbeat_interval = GOSSIPSUB_PARAMS.heartbeat_interval


class PubsubService(ServiceAPI):
    def __init__(
        self,
        host: IHost,
        router: IPubsubRouter | None = None,
        cache_size: int | None = None,
        strict_signing: bool = False,
    ) -> None:
        self.pubsub = Pubsub(host, router, cache_size, strict_signing)
        self.manager: AnyIOManager | None = None

    async def run(self) -> None:
        while (
            self.manager and self.manager.is_running
        ):  # Fixed nested manager reference
            await anyio.sleep(0.1)

    def get_manager(self) -> AnyIOManager | None:
        return self.manager

    async def wait_until_ready(self) -> None:
        await anyio.sleep(0.1)


class PubsubFactory(factory.Factory[Pubsub]):
    class Meta:
        model = Pubsub

    @classmethod
    def _create(cls, model_class: type[Pubsub], **kwargs: Any) -> Pubsub:
        host = kwargs["host"]
        router = kwargs.get("router")
        cache_size = kwargs.get("cache_size")
        strict_signing = kwargs.get("strict_signing", False)
        service = PubsubService(host, router, cache_size, strict_signing)
        return service.pubsub


@asynccontextmanager
async def swarm_create_and_listen(
    key_pair: KeyPair | None = None,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIteratorABC[Swarm]:
    key_pair = key_pair or default_key_pair_factory()
    security_protocol = security_protocol or DEFAULT_SECURITY_PROTOCOL_ID
    muxer_opt = muxer_opt or default_muxer_transport_factory()
    service = SwarmService(key_pair, security_protocol, muxer_opt)
    swarm = service.swarm
    async with background_anyio_service(service):
        await swarm.listen(LISTEN_MADDR)
        yield swarm


@asynccontextmanager
async def swarm_batch_and_listen(
    number: int,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIteratorABC[tuple[Swarm, ...]]:
    async with AsyncExitStack() as stack:
        ctx_mgrs = [
            await stack.enter_async_context(
                swarm_create_and_listen(
                    security_protocol=security_protocol, muxer_opt=muxer_opt
                )
            )
            for _ in range(number)
        ]
        yield tuple(ctx_mgrs)


@asynccontextmanager
async def host_batch_and_listen(
    number: int,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIteratorABC[tuple[BasicHost, ...]]:
    async with swarm_batch_and_listen(number, security_protocol, muxer_opt) as swarms:
        hosts = tuple(BasicHost(swarm) for swarm in swarms)
        yield hosts


@asynccontextmanager
async def routed_host_batch_and_listen(
    number: int,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
) -> AsyncIteratorABC[tuple[RoutedHost, ...]]:
    routing_table = DummyRouter()
    async with host_batch_and_listen(number, security_protocol, muxer_opt) as hosts:
        for host in hosts:
            routing_table._add_peer(host.get_id(), host.get_addrs())
        routed_hosts = tuple(
            RoutedHost(host.get_network(), routing_table) for host in hosts
        )
        yield routed_hosts


@asynccontextmanager
async def pubsub_create_and_start(
    host: IHost,
    router: IPubsubRouter,
    cache_size: int | None,
    seen_ttl: int,
    sweep_interval: int,
    strict_signing: bool,
    msg_id_constructor: Callable[[rpc_pb2.Message], bytes] | None = None,
) -> AsyncIteratorABC[Pubsub]:
    service = PubsubService(host, router, cache_size, strict_signing)
    pubsub = service.pubsub
    async with background_anyio_service(service):
        await service.wait_until_ready()
        yield pubsub


@asynccontextmanager
async def pubsub_batch_with_router(
    number: int,
    routers: Sequence[IPubsubRouter],
    cache_size: int | None = None,
    seen_ttl: int = 120,
    sweep_interval: int = 60,
    strict_signing: bool = False,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
    msg_id_constructor: Callable[[rpc_pb2.Message], bytes] | None = None,
) -> AsyncIteratorABC[tuple[Pubsub, ...]]:
    async with host_batch_and_listen(number, security_protocol, muxer_opt) as hosts:
        async with AsyncExitStack() as stack:
            pubsubs = [
                await stack.enter_async_context(
                    pubsub_create_and_start(
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


@asynccontextmanager
async def pubsub_batch_with_floodsub(
    number: int,
    cache_size: int | None = None,
    seen_ttl: int = 120,
    sweep_interval: int = 60,
    strict_signing: bool = False,
    protocols: Sequence[TProtocol] | None = None,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
    msg_id_constructor: Callable[[rpc_pb2.Message], bytes] = get_peer_and_seqno_msg_id,
) -> AsyncIteratorABC[tuple[Pubsub, ...]]:
    if protocols is not None:
        floodsubs = FloodsubFactory.create_batch(number, protocols=list(protocols))
    else:
        floodsubs = FloodsubFactory.create_batch(number)
    async with pubsub_batch_with_router(
        number,
        floodsubs,
        cache_size,
        seen_ttl,
        sweep_interval,
        strict_signing,
        security_protocol,
        muxer_opt,
        msg_id_constructor,
    ) as pubsubs:
        yield pubsubs


@asynccontextmanager
async def pubsub_batch_with_gossipsub(
    number: int,
    *,
    cache_size: int | None = None,
    strict_signing: bool = False,
    protocols: Sequence[TProtocol] | None = None,
    degree: int = GOSSIPSUB_PARAMS.degree,
    degree_low: int = GOSSIPSUB_PARAMS.degree_low,
    degree_high: int = GOSSIPSUB_PARAMS.degree_high,
    time_to_live: int = GOSSIPSUB_PARAMS.time_to_live,
    gossip_window: int = GOSSIPSUB_PARAMS.gossip_window,
    gossip_history: int = GOSSIPSUB_PARAMS.gossip_history,
    heartbeat_interval: float = GOSSIPSUB_PARAMS.heartbeat_interval,
    heartbeat_initial_delay: float = GOSSIPSUB_PARAMS.heartbeat_initial_delay,
    security_protocol: TProtocol | None = None,
    muxer_opt: TMuxerOptions | None = None,
    msg_id_constructor: Callable[[rpc_pb2.Message], bytes] = get_peer_and_seqno_msg_id,
) -> AsyncIteratorABC[tuple[Pubsub, ...]]:
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
            gossip_window=gossip_window,
            heartbeat_interval=heartbeat_interval,
        )
    async with pubsub_batch_with_router(
        number,
        gossipsubs,
        cache_size,
        seen_ttl=120,
        sweep_interval=60,
        strict_signing=strict_signing,
        security_protocol=security_protocol,
        muxer_opt=muxer_opt,
        msg_id_constructor=msg_id_constructor,
    ) as pubsubs:
        async with AsyncExitStack() as stack:
            for router in gossipsubs:
                await stack.enter_async_context(background_anyio_service(router))
            yield pubsubs


@asynccontextmanager
async def swarm_pair_factory(
    security_protocol: TProtocol | None = None, muxer_opt: TMuxerOptions | None = None
) -> AsyncIteratorABC[tuple[Swarm, Swarm]]:
    async with swarm_batch_and_listen(2, security_protocol, muxer_opt) as swarms:
        await connect_swarm(swarms[0], swarms[1])
        yield swarms[0], swarms[1]


@asynccontextmanager
async def host_pair_factory(
    security_protocol: TProtocol | None = None, muxer_opt: TMuxerOptions | None = None
) -> AsyncIteratorABC[tuple[BasicHost, BasicHost]]:
    async with host_batch_and_listen(2, security_protocol, muxer_opt) as hosts:
        await connect(hosts[0], hosts[1])
        yield hosts[0], hosts[1]


@asynccontextmanager
async def swarm_conn_pair_factory(
    security_protocol: TProtocol | None = None, muxer_opt: TMuxerOptions | None = None
) -> AsyncIteratorABC[tuple[SwarmConn, SwarmConn]]:
    async with swarm_pair_factory(security_protocol, muxer_opt) as swarms:
        conn_0 = swarms[0].connections[swarms[1].get_peer_id()]
        conn_1 = swarms[1].connections[swarms[0].get_peer_id()]
        yield cast(SwarmConn, conn_0), cast(SwarmConn, conn_1)


@asynccontextmanager
async def mplex_conn_pair_factory(
    security_protocol: TProtocol | None = None,
) -> AsyncIteratorABC[tuple[Mplex, Mplex]]:
    async with swarm_conn_pair_factory(
        security_protocol, default_muxer_transport_factory()
    ) as swarm_pair:
        yield cast(Mplex, swarm_pair[0].muxed_conn), cast(
            Mplex, swarm_pair[1].muxed_conn
        )


@asynccontextmanager
async def mplex_stream_pair_factory(
    security_protocol: TProtocol | None = None,
) -> AsyncIteratorABC[tuple[MplexStream, MplexStream]]:
    async with mplex_conn_pair_factory(security_protocol) as mplex_conn_pair_info:
        mplex_conn_0, mplex_conn_1 = mplex_conn_pair_info
        stream_0 = cast(MplexStream, await mplex_conn_0.open_stream())
        await anyio.sleep(0.01)
        async with mplex_conn_1.streams_lock:
            if len(mplex_conn_1.streams) != 1:
                raise Exception("Mplex should not have any other stream")
            stream_1 = tuple(mplex_conn_1.streams.values())[0]
        yield stream_0, stream_1


@asynccontextmanager
async def net_stream_pair_factory(
    security_protocol: TProtocol | None = None, muxer_opt: TMuxerOptions | None = None
) -> AsyncIteratorABC[tuple[INetStream, INetStream]]:
    protocol_id = TProtocol("/example/id/1")
    stream_1: INetStream | None = None
    event_handler_finished = anyio.Event()

    async def handler(stream: INetStream) -> None:
        nonlocal stream_1
        stream_1 = stream
        await event_handler_finished.wait()

    async with host_pair_factory(security_protocol, muxer_opt) as hosts:
        hosts[1].set_stream_handler(protocol_id, handler)
        stream_0 = await hosts[0].new_stream(hosts[1].get_id(), [protocol_id])
        if stream_1 is None:
            raise ValueError("Stream 1 not established")
        yield stream_0, stream_1
        event_handler_finished.set()

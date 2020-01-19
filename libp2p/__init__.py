from typing import AsyncIterator, Sequence

from async_generator import asynccontextmanager
from async_service import background_trio_service

from libp2p.crypto.keys import KeyPair
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from libp2p.host.host_interface import IHost
from libp2p.host.routed_host import RoutedHost
from libp2p.network.network_interface import INetwork, INetworkService
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.routing.interfaces import IPeerRouting
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
import libp2p.security.secio.transport as secio
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.typing import TMuxerOptions, TSecurityOptions
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.typing import TProtocol


def generate_new_rsa_identity() -> KeyPair:
    return create_new_key_pair()


def generate_peer_id_from(key_pair: KeyPair) -> ID:
    public_key = key_pair.public_key
    return ID.from_pubkey(public_key)


def initialize_default_swarm(
    key_pair: KeyPair = None,
    muxer_opt: TMuxerOptions = None,
    sec_opt: TSecurityOptions = None,
    peerstore_opt: IPeerStore = None,
) -> INetworkService:
    """
    initialize swarm when no swarm is passed in.

    :param key_pair: optional choice of the ``KeyPair``
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :return: return a default swarm instance
    """

    if not key_pair:
        key_pair = generate_new_rsa_identity()

    id_opt = generate_peer_id_from(key_pair)

    # TODO: Parse `listen_addrs` to determine transport
    transport = TCP()

    muxer_transports_by_protocol = muxer_opt or {MPLEX_PROTOCOL_ID: Mplex}
    security_transports_by_protocol = sec_opt or {
        TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair),
        TProtocol(secio.ID): secio.Transport(key_pair),
    }
    upgrader = TransportUpgrader(
        security_transports_by_protocol, muxer_transports_by_protocol
    )

    peerstore = peerstore_opt or PeerStore()
    # Store our key pair in peerstore
    peerstore.add_key_pair(id_opt, key_pair)

    return Swarm(id_opt, peerstore, upgrader, transport)


def _new_host(swarm_opt: INetwork, disc_opt: IPeerRouting = None) -> IHost:
    """
    create new libp2p host.

    :param swarm_opt: optional swarm
    :param disc_opt: optional discovery
    :return: return a host instance
    """
    # TODO enable support for other host type
    # TODO routing unimplemented
    host: IHost  # If not explicitly typed, MyPy raises error
    if disc_opt:
        host = RoutedHost(swarm_opt, disc_opt)
    else:
        host = BasicHost(swarm_opt)

    return host


@asynccontextmanager
async def new_host_trio(
    listen_addrs: Sequence[str],
    key_pair: KeyPair = None,
    swarm_opt: INetwork = None,
    muxer_opt: TMuxerOptions = None,
    sec_opt: TSecurityOptions = None,
    peerstore_opt: IPeerStore = None,
    disc_opt: IPeerRouting = None,
) -> AsyncIterator[IHost]:
    swarm = initialize_default_swarm(
        key_pair=key_pair,
        muxer_opt=muxer_opt,
        sec_opt=sec_opt,
        peerstore_opt=peerstore_opt,
    )
    async with background_trio_service(swarm):
        await swarm.listen(*listen_addrs)
        host = _new_host(swarm_opt=swarm, disc_opt=disc_opt)
        yield host


# TODO: Support asyncio

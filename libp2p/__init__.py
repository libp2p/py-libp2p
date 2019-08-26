import asyncio
from typing import Mapping, Sequence

from libp2p.crypto.keys import KeyPair
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from libp2p.kademlia.network import KademliaServer
from libp2p.kademlia.storage import IStorage
from libp2p.network.network_interface import INetwork
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.routing.interfaces import IPeerRouting
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
import libp2p.security.secio.transport as secio
from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.stream_muxer.muxer_multistream import MuxerClassType
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.typing import TProtocol


async def cleanup_done_tasks() -> None:
    """
    clean up asyncio done tasks to free up resources
    """
    while True:
        for task in asyncio.all_tasks():
            if task.done():
                await task

        # Need not run often
        # Some sleep necessary to context switch
        await asyncio.sleep(3)


def generate_new_rsa_identity() -> KeyPair:
    return create_new_key_pair()


def generate_peer_id_from_rsa_identity(key_pair: KeyPair = None) -> ID:
    if not key_pair:
        key_pair = generate_new_rsa_identity()
    public_key = key_pair.public_key
    return ID.from_pubkey(public_key)


def initialize_default_kademlia_router(
    ksize: int = 20, alpha: int = 3, id_opt: ID = None, storage: IStorage = None
) -> KadmeliaPeerRouter:
    """
    initialize kadmelia router when no kademlia router is passed in
    :param ksize: The k parameter from the paper
    :param alpha: The alpha parameter from the paper
    :param id_opt: optional id for host
    :param storage: An instance that implements
        :interface:`~kademlia.storage.IStorage`
    :return: return a default kademlia instance
    """
    if not id_opt:
        id_opt = generate_peer_id_from_rsa_identity()

    node_id = id_opt.to_bytes()
    # ignore type for Kademlia module
    server = KademliaServer(  # type: ignore
        ksize=ksize, alpha=alpha, node_id=node_id, storage=storage
    )
    return KadmeliaPeerRouter(server)


def initialize_default_swarm(
    key_pair: KeyPair,
    id_opt: ID = None,
    transport_opt: Sequence[str] = None,
    muxer_opt: Mapping[TProtocol, MuxerClassType] = None,
    sec_opt: Mapping[TProtocol, ISecureTransport] = None,
    peerstore_opt: IPeerStore = None,
    disc_opt: IPeerRouting = None,
) -> Swarm:
    """
    initialize swarm when no swarm is passed in
    :param id_opt: optional id for host
    :param transport_opt: optional choice of transport upgrade
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param disc_opt: optional discovery
    :return: return a default swarm instance
    """

    if not id_opt:
        id_opt = generate_peer_id_from_rsa_identity(key_pair)

    # TODO: Parse `transport_opt` to determine transport
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
    # TODO: Initialize discovery if not presented
    return Swarm(id_opt, peerstore, upgrader, transport, disc_opt)


async def new_node(
    key_pair: KeyPair = None,
    swarm_opt: INetwork = None,
    id_opt: ID = None,
    transport_opt: Sequence[str] = None,
    muxer_opt: Mapping[TProtocol, MuxerClassType] = None,
    sec_opt: Mapping[TProtocol, ISecureTransport] = None,
    peerstore_opt: IPeerStore = None,
    disc_opt: IPeerRouting = None,
) -> BasicHost:
    """
    create new libp2p node
    :param key_pair: key pair for deriving an identity
    :param swarm_opt: optional swarm
    :param id_opt: optional id for host
    :param transport_opt: optional choice of transport upgrade
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param disc_opt: optional discovery
    :return: return a host instance
    """

    if not key_pair:
        key_pair = generate_new_rsa_identity()

    if not id_opt:
        id_opt = generate_peer_id_from_rsa_identity(key_pair)

    if not swarm_opt:
        swarm_opt = initialize_default_swarm(
            key_pair=key_pair,
            id_opt=id_opt,
            transport_opt=transport_opt,
            muxer_opt=muxer_opt,
            sec_opt=sec_opt,
            peerstore_opt=peerstore_opt,
            disc_opt=disc_opt,
        )

    # TODO enable support for other host type
    # TODO routing unimplemented
    host = BasicHost(swarm_opt)

    # Kick off cleanup job
    asyncio.ensure_future(cleanup_done_tasks())

    return host

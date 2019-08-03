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
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.security.secure_transport_interface import ISecureTransport
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


def generate_peer_id_from_rsa_identity(key_pair=None) -> ID:
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
    private_key: bytes,
    id_opt: ID = None,
    transport_opt: Sequence[str] = None,
    muxer_opt: Sequence[str] = None,
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
        id_opt = generate_peer_id_from_rsa_identity()

    # TODO parse transport_opt to determine transport
    transport_opt = transport_opt or ["/ip4/127.0.0.1/tcp/8001"]
    transport = TCP()

    # TODO TransportUpgrader is not doing anything really
    # TODO parse muxer and sec to pass into TransportUpgrader
    muxer = muxer_opt or ["mplex/6.7.0"]
    private_key_bytes = private_key.export_key("DER")
    public_key_bytes = private_key.publickey().export_key("DER")
    security_transports_by_protocol = sec_opt or {
        TProtocol("insecure/1.0.0"): InsecureTransport(
            private_key_bytes, public_key_bytes
        )
    }
    upgrader = TransportUpgrader(security_transports_by_protocol, muxer)

    peerstore = peerstore_opt or PeerStore()
    # TODO: Initialize discovery if not presented
    swarm_opt = Swarm(id_opt, peerstore, upgrader, transport, disc_opt)

    return swarm_opt


async def new_node(
    private_key=None,
    swarm_opt: INetwork = None,
    id_opt: ID = None,
    transport_opt: Sequence[str] = None,
    muxer_opt: Sequence[str] = None,
    sec_opt: Mapping[TProtocol, ISecureTransport] = None,
    peerstore_opt: IPeerStore = None,
    disc_opt: IPeerRouting = None,
) -> BasicHost:
    """
    create new libp2p node
    :param swarm_opt: optional swarm
    :param id_opt: optional id for host
    :param transport_opt: optional choice of transport upgrade
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :param disc_opt: optional discovery
    :return: return a host instance
    """

    if not private_key:
        key_pair = generate_new_rsa_identity()
        private_key = key_pair.private_key

    if not id_opt:
        id_opt = generate_peer_id_from_rsa_identity(key_pair)

    if not swarm_opt:
        swarm_opt = initialize_default_swarm(
            private_key=private_key,
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

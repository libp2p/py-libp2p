import asyncio
from typing import Mapping, Sequence

from Crypto.PublicKey import RSA
from libp2p.kademlia.storage import IStorage
from libp2p.network.network_interface import INetwork
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.routing.interfaces import IPeerRouting
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.security.secure_transport_interface import ISecureTransport

from .host.basic_host import BasicHost
from .kademlia.network import KademliaServer
from .network.swarm import Swarm
from .peer.id import ID
from .peer.peerstore import PeerStore
from .routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter
from .transport.tcp.tcp import TCP
from .transport.upgrader import TransportUpgrader
from .typing import TProtocol


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


def generate_new_private_key():
    new_key = RSA.generate(2048, e=65537)
    return new_key


def generate_id(private_key):
    public_key_bytes = private_key.publickey().export_key("DER")
    new_id = ID.from_pubkey(public_key_bytes)
    return new_id


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
        id_opt = generate_id(generate_new_private_key())

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
        id_opt = generate_id(private_key)

    # TODO parse transport_opt to determine transport
    transport_opt = transport_opt or ["/ip4/127.0.0.1/tcp/8001"]
    transport = TCP()

    # TODO TransportUpgrader is not doing anything really
    # TODO parse muxer and sec to pass into TransportUpgrader
    muxer = muxer_opt or ["mplex/6.7.0"]
    private_key_bytes = private_key.export_key("DER")
    security_transports_by_protocol = sec_opt or {
        TProtocol("insecure/1.0.0"): InsecureTransport(private_key_bytes)
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
        private_key = generate_new_private_key()

    if not id_opt:
        id_opt = generate_id(private_key)

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

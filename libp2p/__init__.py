import asyncio
import multiaddr

from Crypto.PublicKey import RSA
from .peer.peerstore import PeerStore
from .peer.id import id_from_public_key
from .network.swarm import Swarm
from .host.basic_host import BasicHost
from .kademlia.routed_host import RoutedHost
from .transport.upgrader import TransportUpgrader
from .transport.tcp.tcp import TCP
from .kademlia.network import KademliaServer
from libp2p.security.insecure_security import InsecureTransport


async def cleanup_done_tasks():
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

def generate_id():
    new_key = RSA.generate(2048, e=65537)
    new_id = id_from_public_key(new_key.publickey())
    # private_key = new_key.exportKey("PEM")
    return new_id

def initialize_default_kademlia(
        ksize=20, alpha=3, id_opt=None, storage=None):
    """
    initialize swam when no swarm is passed in
    :param ksize: The k parameter from the paper
    :param alpha: The alpha parameter from the paper
    :param id_opt: optional id for host
    :param storage: An instance that implements
        :interface:`~kademlia.storage.IStorage`
    :return: return a default kademlia instance
    """
    if not id_opt:
        id_opt = generate_id()

    node_id = id_opt.get_raw_id()
    return KademliaServer(ksize=ksize, alpha=alpha,
                          node_id=node_id, storage=storage)


def initialize_default_swarm(
        id_opt=None, transport_opt=None,
        muxer_opt=None, sec_opt=None, peerstore_opt=None):
    """
    initialize swarm when no swarm is passed in
    :param id_opt: optional id for host
    :param transport_opt: optional choice of transport upgrade
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :return: return a default swarm instance
    """
    # pylint: disable=too-many-arguments, unused-argument

    if not id_opt:
        id_opt = generate_id()

    transport_opt = transport_opt or ["/ip4/127.0.0.1/tcp/8001"]
    transport = [multiaddr.Multiaddr(t) for t in transport_opt]
    # TODO wire muxer up with swarm
    # muxer = muxer_opt or ["mplex/6.7.0"]

    # Use passed in security option or the default insecure option
    sec = sec_opt or {"/insecure/1.0.0": InsecureTransport("insecure")}
    peerstore = peerstore_opt or PeerStore()
    upgrader = TransportUpgrader(sec, transport)
    swarm_opt = Swarm(id_opt, peerstore, upgrader)
    tcp = TCP()
    swarm_opt.add_transport(tcp)

    return swarm_opt


async def new_node(
        swarm_opt=None, id_opt=None, transport_opt=None,
        muxer_opt=None, sec_opt=None, peerstore_opt=None,
        disc_opt=None):
    """
    create new libp2p node
    :param id_opt: optional id for host
    :param transport_opt: optional choice of transport upgrade
    :param muxer_opt: optional choice of stream muxer
    :param sec_opt: optional choice of security upgrade
    :param peerstore_opt: optional peerstore
    :return: return a default swarm instance
    """
    # pylint: disable=too-many-arguments

    if not id_opt:
        id_opt = generate_id()

    if not swarm_opt:
        swarm_opt = initialize_default_swarm(
            id_opt=id_opt, transport_opt=transport_opt,
            muxer_opt=muxer_opt, sec_opt=sec_opt,
            peerstore_opt=peerstore_opt)

    # TODO enable support for other host type
    # TODO routing unimplemented
    if not disc_opt:
        host = BasicHost(swarm_opt)
    else:
        host = RoutedHost(swarm_opt, disc_opt)

    # Kick off cleanup job
    asyncio.ensure_future(cleanup_done_tasks())

    return host

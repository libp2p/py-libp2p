from Crypto.PublicKey import RSA

import multiaddr

from .peer.peerstore import PeerStore
from .peer.id import id_from_public_key
from .network.swarm import Swarm
from .host.basic_host import BasicHost
from .transport.upgrader import TransportUpgrader
from .transport.tcp.tcp import TCP


async def new_node(
        id_opt=None, transport_opt=None,
        muxer_opt=None, sec_opt=None, peerstore=None):

    if id_opt is None:
        new_key = RSA.generate(2048, e=65537)
        id_opt = id_from_public_key(new_key.publickey())
        # private_key = new_key.exportKey("PEM")

    transport_opt = transport_opt or ["/ip4/127.0.0.1/tcp/8001"]
    transport_opt = [multiaddr.Multiaddr(t) for t in transport_opt]
    muxer_opt = muxer_opt or ["mplex/6.7.0"]
    sec_opt = sec_opt or ["secio"]
    peerstore = peerstore or PeerStore()

    upgrader = TransportUpgrader(sec_opt, transport_opt)
    swarm = Swarm(id_opt, peerstore, upgrader)
    tcp = TCP()
    swarm.add_transport(tcp)
    await swarm.listen(transport_opt[0])

    # TODO enable support for other host type
    # TODO routing unimplemented
    host = BasicHost(swarm)

    return host

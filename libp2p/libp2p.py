from Crypto.PublicKey import RSA
from peer.peerstore import PeerStore
from peer.id import id_from_public_key
from network.swarm import Swarm
from host.basic_host import BasicHost
from transport.upgrader import TransportUpgrader
from transport.tcp.tcp import TCP
import multiaddr


<<<<<<< HEAD
async def new_node(id_opt=None, transport_opt=None, \
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
=======
class Libp2p():

    def __init__(self, id_opt=None, transport_opt=["/ip4/127.0.0.1/tcp/8001"],
                 muxer_opt=["mplex/6.7.0"], sec_opt=["secio"], peerstore=None):

        if id_opt:
            self.id_opt = id_opt
        else:
            new_key = RSA.generate(2048, e=65537)
            self.id_opt = id_from_public_key(new_key.publickey())
            self.private_key = new_key.exportKey("PEM")

        # convert into Multiaddr
        self.transport_opt = [multiaddr.Multiaddr(t) for t in transport_opt]
        self.muxer_opt = muxer_opt
        self.sec_opt = sec_opt
        self.peerstore = peerstore or PeerStore()

    async def new_node(self):

        upgrader = TransportUpgrader(self.sec_opt, self.transport_opt)
        swarm = Swarm(self.id_opt, self.peerstore, upgrader)
        tcp = TCP()
        swarm.add_transport(tcp)
        await swarm.listen(self.transport_opt[0])
        host = BasicHost(swarm)

        # TODO MuxedConnection currently contains all muxing logic (move to a Muxer)
        # TODO routing unimplemented
        return host
>>>>>>> don't instanciate peerstore object in constructor

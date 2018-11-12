from peer.peerstore import PeerStore
from network.swarm import Swarm
from host.basic_host import BasicHost
from transport.upgrader import TransportUpgrader
from transport.tcp.tcp import TCP
from Crypto.PublicKey import RSA

class Libp2p(object):

    def __init__(self, idOpt = None, \
        transportOpt = ["/ip4/127.0.0.1/tcp/8001"], \
        muxerOpt = ["mplex/6.7.0"], \
        secOpt = ["secio"], \
        peerstore = PeerStore()):
        
        if idOpt:
            self.idOpt = idOpt
        else:
            new_key = RSA.generate(2048, e=65537)
            self.idOpt = new_key.publickey().exportKey("PEM")
            self.private_key = new_key.exportKey("PEM")
      
        self.transportOpt = transportOpt
        self.muxerOpt = muxerOpt
        self.secOpt = secOpt
        self.peerstore = peerstore

    async def new_node(self):

        upgrader = TransportUpgrader(self.secOpt, self.transportOpt)
        swarm = Swarm(self.idOpt, self.peerstore, upgrader)
        tcp = TCP()
        swarm.add_transport(tcp)
        await swarm.listen(self.transportOpt[0])
        host = BasicHost(swarm)

        # TODO MuxedConnection currently contains all muxing logic (move to a Muxer)
        # TODO routing unimplemented
        return host

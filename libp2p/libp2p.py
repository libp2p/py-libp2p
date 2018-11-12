from peer.peerstore import PeerStore
from network.swarm import Swarm
from host.basic_host import BasicHost
from transport.upgrader import TransportUpgrader
from Crypto.PublicKey import RSA

class Libp2p(object):

    def __init__(self, idOpt = None, \
        transportOpt = ["/ip4/127.0.0.1/tcp/10000"], \
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

    def new_node(self):

        swarm = Swarm(self.idOpt, self.peerstore)
        host = BasicHost(swarm)
        upgrader = TransportUpgrader(self.secOpt, self.muxerOpt)

        # TODO transport upgrade

        # TODO listen on addrs

        # TODO swarm add transports

        # TODO: return host

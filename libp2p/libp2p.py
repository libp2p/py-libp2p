from ..peer.peerstore import PeerStore
from ..network.swarm import Swarm
from ..host.basic_host import BasicHost
from ..transport.upgrader import TransportUpgrader

class Libp2p(object):

    def __init__(self, idOpt, \
        transportOpt = ["/ip4/127.0.0.1/tcp/10000"], \
        muxerOpt = ["mplex/6.7.0"], \
        secOpt = ["secio"], \
        peerstore = PeerStore()):
        
        if idOpt:
            self.idOpt = idOpt
        else:
            # TODO generate RSA public key pair
            pass

        self.transportOpt = transportOpt
        self.muxerOpt =  muxerOpt
        self.secOpt = secOpt
        self.peerstore = peerstore

    def new_node(self):

        swarm = Swarm(self.id, self.peerstore)
        host = BasicHost(swarm)
        upgrader = TransportUpgrader(self.secOpt, self.transportOpt)

        # TODO transport upgrade

        # TODO listen on addrs

        # TODO swarm add transports

        # TODO: return host

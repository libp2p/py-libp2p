from .config import Config
from ..peer.peerstore import PeerStore

class Libp2p(object):

    def __init__(self, idOpt, \
        transportOpt = ["/ip4/0.0.0.0/tcp/0"], \
        muxerOpt = ["mplex/6.7.0"], \
        secOpt = ["secio"], \
        peerstoreOpt = new PeerStore()):
        
        if idOpt:
            self.idOpt = idOpt
        else:
            # TODO generate RSA public key pair

        # TODO initialize 

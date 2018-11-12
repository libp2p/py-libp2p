from Crypto.PublicKey import RSA
from peer.peerstore import PeerStore
from network.swarm import Swarm
from host.basic_host import BasicHost
from transport.upgrader import TransportUpgrader
from transport.tcp.tcp import TCP


class Libp2p():

    def __init__(self, id_opt=None, transport_opt=["/ip4/127.0.0.1/tcp/8001"], \
        muxer_opt=["mplex/6.7.0"], sec_opt=["secio"], peerstore=PeerStore()):

        if id_opt:
            self.id_opt = id_opt
        else:
            new_key = RSA.generate(2048, e=65537)
            self.id_opt = new_key.publickey().exportKey("PEM")
            self.private_key = new_key.exportKey("PEM")

        self.transport_opt = transport_opt
        self.muxer_opt = muxer_opt
        self.sec_opt = sec_opt
        self.peerstore = peerstore

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

import msgpack

from libp2p.peer.id import id_b58_decode
from libp2p.kademlia.network import Server
from libp2p.kademlia.node import Node
from libp2p.kademlia.utils import digest
from libp2p.kademlia.crawling import ValueMultipleSpiderCrawl
from libp2p.discovery.advertiser_interface import IAdvertiser
from libp2p.discovery.discoverer_interface import IDiscoverer

from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerdata import PeerData


class KademliaPeerRouter(IAdvertiser, IDiscoverer):

    def __init__(self, host, bootstrap_nodes=None):
        self.host = host
        self.peer_id = host.get_id()
        self.bootstrap_nodes = bootstrap_nodes
        self.node = Server()

    async def listen(self, port):
        await self.node.listen(port)
        if self.bootstrap_nodes:
            await self.node.bootstrap(self.bootstrap_nodes)

    async def advertise(self, service):
        await self.node.set(service, self._make_advertise_msg())

    def _make_advertise_msg(self):
        peer_data = PeerData()
        peer_data.add_addrs(self.host.get_addrs())
        peer_info = PeerInfo(self.peer_id, peer_data)

        if len(peer_info.addrs) < 1:
            raise RuntimeError("not know address for self")

        return encode_peer_info(peer_info)

    async def find_peers(self, service):
        key = dht_key(service)
        target = Node(key)

        nearest = self.node.protocol.router.find_neighbors(target)
        if not nearest:
            print("There are no known neighbors to get key %s", key)
            return []
        spider = ValueMultipleSpiderCrawl(self.node.protocol, target, nearest,
                                          self.node.ksize, self.node.alpha)

        values = await spider.find()
        if values:
            return list(map(decode_peer_info, values))
        return []


def dht_key(service):
    # TODO: should convert to Content Identification
    return digest(service)


def encode_peer_info(peer_info):
    return msgpack.dumps({
        'peer_id': peer_info.peer_id.pretty(),
        'addrs': [str(ma) for ma in peer_info.addrs]
    })


def decode_peer_info(data):
    info = msgpack.loads(data, raw=False)

    peer_id = id_b58_decode(info['peer_id'])
    peer_data = PeerData()
    peer_data.add_addrs(info['addrs'])

    return PeerInfo(peer_id, peer_data)

from libp2p.routing.interfaces import IPeerRouting
from libp2p.kademlia.utils import digest
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerdata import PeerData


class KadmeliaPeerRouter(IPeerRouting):

    def __init__(self, dht_server):
        self.server = dht_server

    def find_peer(self, peer_id):
        """
        Find specific Peer
        FindPeer searches for a peer with given peer_id, returns a peer.PeerInfo
        with relevant addresses.
        """
        value = self.server.get(peer_id)
        return decode_peerinfo(value)


def decode_peerinfo(encoded):
    if isinstance(encoded, bytes):
        encoded = encoded.decode()
    lines = encoded.splitlines()
    peer_id = lines[0]
    addrs = lines[1:]
    peer_data = PeerData()
    peer_data.add_addrs(addrs)
    return PeerInfo(peer_id, addrs)

import ast

from libp2p.routing.interfaces import IPeerRouting
from libp2p.kademlia.kad_peerinfo import create_kad_peerinfo


class KadmeliaPeerRouter(IPeerRouting):
    # pylint: disable=too-few-public-methods

    def __init__(self, dht_server):
        self.server = dht_server

    async def find_peer(self, peer_id):
        """
        Find specific Peer
        FindPeer searches for a peer with given peer_id, returns a peer.PeerInfo
        with relevant addresses.
        """
        # switching peer_id to xor_id used by kademlia as node_id
        xor_id = peer_id.get_xor_id()
        value = await self.server.get(xor_id)
        return decode_peerinfo(value)

def decode_peerinfo(encoded):
    if isinstance(encoded, bytes):
        encoded = encoded.decode()
    print(encoded)
    try:
        lines = ast.literal_eval(encoded)
    except SyntaxError:
        return None
    # xor_id = lines[0]
    ip = lines[1] # pylint: disable=invalid-name
    port = lines[2]
    peer_id = lines[3]
    peer_info = create_kad_peerinfo(peer_id, ip, port)
    return peer_info

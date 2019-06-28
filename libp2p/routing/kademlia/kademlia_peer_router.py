import ast

from libp2p.kademlia.kad_peerinfo import create_kad_peerinfo
from libp2p.routing.interfaces import IPeerRouting


class KadmeliaPeerRouter(IPeerRouting):
    def __init__(self, dht_server):
        self.server = dht_server

    async def find_peer(self, peer_id):
        """
        Find a specific peer
        :param peer_id: peer to search for
        :return: KadPeerInfo of specified peer
        """
        # switching peer_id to xor_id used by kademlia as node_id
        xor_id = peer_id.get_xor_id()
        value = await self.server.get(xor_id)
        return decode_peerinfo(value)


def decode_peerinfo(encoded):
    if isinstance(encoded, bytes):
        encoded = encoded.decode()
    try:
        lines = ast.literal_eval(encoded)
    except SyntaxError:
        return None
    ip = lines[1]
    port = lines[2]
    peer_id = lines[3]
    peer_info = create_kad_peerinfo(peer_id, ip, port)
    return peer_info

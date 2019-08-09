import ast
from typing import Union

from libp2p.kademlia.kad_peerinfo import KadPeerInfo, create_kad_peerinfo
from libp2p.kademlia.network import KademliaServer
from libp2p.peer.id import ID
from libp2p.routing.interfaces import IPeerRouting


class KadmeliaPeerRouter(IPeerRouting):

    server: KademliaServer

    def __init__(self, dht_server: KademliaServer) -> None:
        self.server = dht_server

    async def find_peer(self, peer_id: ID) -> KadPeerInfo:
        """
        Find a specific peer
        :param peer_id: peer to search for
        :return: KadPeerInfo of specified peer
        """
        # switching peer_id to xor_id used by kademlia as node_id
        xor_id = peer_id.xor_id
        # ignore type for kad
        value = await self.server.get(xor_id)  # type: ignore
        return decode_peerinfo(value)


def decode_peerinfo(encoded: Union[bytes, str]) -> KadPeerInfo:
    if isinstance(encoded, bytes):
        encoded = encoded.decode()
    try:
        lines = ast.literal_eval(encoded)
    except SyntaxError:
        return None
    ip = lines[1]
    port = lines[2]
    peer_id = lines[3]
    # ignore typing for kad
    peer_info = create_kad_peerinfo(peer_id, ip, port)  # type: ignore
    return peer_info

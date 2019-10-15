from libp2p.kademlia.network import KademliaServer
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.routing.interfaces import IPeerRouting


class KadmeliaPeerRouter(IPeerRouting):
    server: KademliaServer

    def __init__(self, dht_server: KademliaServer) -> None:
        self.server = dht_server

    async def find_peer(self, peer_id: ID) -> PeerInfo:
        """
        Find a specific peer
        :param peer_id: peer to search for
        :return: PeerInfo of specified peer
        """
        # switching peer_id to xor_id used by kademlia as node_id
        xor_id = peer_id.xor_id
        # ignore type for kad
        value = await self.server.get(xor_id)  # type: ignore
        return (
            PeerInfo.info_from_string(value) if value else None
        )  # TODO: should raise error if None?

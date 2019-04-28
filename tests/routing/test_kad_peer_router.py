import asyncio
import pytest

from libp2p.kademlia.network import KademliaServer
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter
from libp2p.peer.id import id_b58_encode

@pytest.mark.asyncio
async def test_example():
    node_a = KademliaServer()
    await node_a.listen(5678)

    node_b = KademliaServer()
    await node_b.listen(5679)

    value = await node_b.bootstrap([("127.0.0.1", 5678)])
    peer_info = value[0]
    peer_id = peer_info.peer_id_obj
    print(id_b58_encode(peer_id))
    # await node_a.set(peer_info.xor_id, str(peer_info.ip) + "/" + str(peer_info.port))
    # router = KadmeliaPeerRouter(node_b)
    # value = await router.find_peer(peer_id)
    # print("value vvvv")
    # print(value.xor_)
    # assert value == str(peer_info.ip) + "/" + str(peer_info.port)

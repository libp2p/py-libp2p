import pytest

from libp2p.kademlia.network import KademliaServer
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter

@pytest.mark.asyncio
async def test_simple_two_nodes():
    node_a = KademliaServer()
    await node_a.listen(5678)

    node_b = KademliaServer()
    await node_b.listen(5679)

    node_a_value = await node_b.bootstrap([("127.0.0.1", 5678)])
    node_a_kad_peerinfo = node_a_value[0]

    await node_a.set(node_a_kad_peerinfo.xor_id,
                     str(node_a_kad_peerinfo.ip)\
                     + "/" + str(node_a_kad_peerinfo.port))

    router = KadmeliaPeerRouter(node_b)
    returned_info = await router.find_peer(node_a_kad_peerinfo.peer_id_obj)
    assert returned_info == str(node_a_kad_peerinfo.ip)\
                            + "/" + str(node_a_kad_peerinfo.port)

@pytest.mark.asyncio
async def test_simple_three_nodes():
    node_a = KademliaServer()
    await node_a.listen(5701)

    node_b = KademliaServer()
    await node_b.listen(5702)

    node_c = KademliaServer()
    await node_c.listen(5703)

    node_a_value = await node_b.bootstrap([("127.0.0.1", 5701)])
    node_a_kad_peerinfo = node_a_value[0]

    await node_c.bootstrap([("127.0.0.1", 5702)])
    await node_a.set(node_a_kad_peerinfo.xor_id,
                     str(node_a_kad_peerinfo.ip)\
                     + "/" + str(node_a_kad_peerinfo.port))

    router = KadmeliaPeerRouter(node_c)
    returned_info = await router.find_peer(node_a_kad_peerinfo.peer_id_obj)
    assert returned_info == str(node_a_kad_peerinfo.ip) + "/" + str(node_a_kad_peerinfo.port)

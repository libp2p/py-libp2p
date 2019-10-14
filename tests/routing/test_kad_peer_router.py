import pytest

from libp2p.kademlia.network import KademliaServer
from libp2p.peer.id import ID
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter


@pytest.mark.asyncio
async def test_simple_two_nodes():
    node_a = KademliaServer()
    await node_a.listen(5678)

    node_b = KademliaServer()
    await node_b.listen(5679)

    node_a_value = await node_b.bootstrap([("127.0.0.1", 5678)])
    node_a_kad_peerinfo = node_a_value[0]
    await node_a.set(node_a_kad_peerinfo.xor_id, node_a_kad_peerinfo.to_string())

    router = KadmeliaPeerRouter(node_b)
    returned_info = await router.find_peer(ID(node_a_kad_peerinfo.peer_id_bytes))
    assert returned_info == node_a_kad_peerinfo


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
    await node_a.set(node_a_kad_peerinfo.xor_id, node_a_kad_peerinfo.to_string())

    router = KadmeliaPeerRouter(node_c)
    returned_info = await router.find_peer(ID(node_a_kad_peerinfo.peer_id_bytes))
    assert returned_info == node_a_kad_peerinfo


@pytest.mark.asyncio
async def test_simple_four_nodes():
    node_a = KademliaServer()
    await node_a.listen(5801)

    node_b = KademliaServer()
    await node_b.listen(5802)

    node_c = KademliaServer()
    await node_c.listen(5803)

    node_d = KademliaServer()
    await node_d.listen(5804)

    node_a_value = await node_b.bootstrap([("127.0.0.1", 5801)])
    node_a_kad_peerinfo = node_a_value[0]

    await node_c.bootstrap([("127.0.0.1", 5802)])

    await node_d.bootstrap([("127.0.0.1", 5803)])

    await node_b.set(node_a_kad_peerinfo.xor_id, node_a_kad_peerinfo.to_string())

    router = KadmeliaPeerRouter(node_d)
    returned_info = await router.find_peer(ID(node_a_kad_peerinfo.peer_id_bytes))
    assert returned_info == node_a_kad_peerinfo

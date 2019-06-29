from typing import List

import pytest

from libp2p.kademlia.network import KademliaServer
from libp2p.peer.id import ID
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter


@pytest.fixture
async def nodes():
    class NodeFactory:
        def __init__(self):
            self._nodes: List[KademliaServer] = []

        async def get(self, port) -> KademliaServer:
            n = KademliaServer()
            await n.listen(port)
            self._nodes.append(n)
            return n

        def stop(self):
            for node in self._nodes:
                node.stop()

    factory = NodeFactory()
    yield factory

    factory.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("node_count", [2, 3, 4])
async def test_simple_nodes(nodes, node_count):
    port = 5600
    node = await nodes.get(port)

    peer_kad_peerinfos = []
    for offset in range(1, node_count):
        peer_port = port + offset
        peer = await nodes.get(peer_port)
        peer_value = await node.bootstrap([("127.0.0.1", peer_port)])
        peer_kad_peerinfo = peer_value[0]
        await peer.set(peer_kad_peerinfo.xor_id, repr(peer_kad_peerinfo))
        peer_kad_peerinfos.append(peer_kad_peerinfo)

    node.refresh_table()
    router = KadmeliaPeerRouter(node)

    for peer_kad_peerinfo in peer_kad_peerinfos:
        returned_info = await router.find_peer(peer_kad_peerinfo.peer_id_obj)
        assert repr(returned_info) == repr(peer_kad_peerinfo)


@pytest.mark.asyncio
async def test_bootstrappable_neighbors(nodes):
    port = 5600
    node = await nodes.get(port)

    # initialise a peer node
    peer_port = port + 1
    await nodes.get(peer_port)

    neighbours = [("127.0.0.1", peer_port)]
    await node.bootstrap(neighbours)

    assert node.bootstrappable_neighbors() == neighbours


@pytest.mark.asyncio
async def test_set_get_key(nodes):
    port = 5600
    node = await nodes.get(port)

    peer_port = port + 1
    peer = await nodes.get(peer_port)

    await node.bootstrap([("127.0.0.1", peer_port)])

    local_id = ID("local")
    await node.set(local_id.get_xor_id(), repr(local_id))

    remote_id = ID("remote")
    await peer.set(remote_id.get_xor_id(), repr(remote_id))

    assert await node.get(local_id.get_xor_id()) == repr(local_id)
    assert await node.get(remote_id.get_xor_id()) == repr(remote_id)


@pytest.mark.asyncio
async def test_state_save_load(tmpdir, nodes):
    port = 5600
    node = await nodes.get(port)

    peer_port = port + 1
    peer = await nodes.get(peer_port)

    await node.bootstrap([("127.0.0.1", peer_port)])

    state_file_path = tmpdir.join("kad.state")
    peer.save_state(state_file_path)
    assert state_file_path.exists()
    peer.stop()

    recovered_peer = KademliaServer.load_state(state_file_path)
    await recovered_peer.listen(peer_port)

    assert recovered_peer.ksize == peer.ksize
    assert recovered_peer.alpha == peer.alpha
    assert recovered_peer.node.peer_id == peer.node.peer_id
    # This does not work right now since the load_state method is incorrect
    # assert recovered_peer.bootstrappable_neighbors() == peer.bootstrappable_neighbors()


@pytest.mark.asyncio
async def test_state_save_skip_if_no_neighbours(tmpdir, nodes):
    port = 5600
    node = await nodes.get(port)

    state_file_path = tmpdir.join("kad.state")
    node.save_state(state_file_path)
    assert not state_file_path.exists()

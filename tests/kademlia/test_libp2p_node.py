import multiaddr
import pytest
from libp2p import new_node
from libp2p.host.routed_host import RoutedHost
from libp2p.kademlia.network import Server
from libp2p.discovery.kademlia_router import KademliaPeerRouter
from libp2p.peer.peerinfo import info_from_p2p_addr


# @pytest.mark.asyncio
# async def test_connect_to_peer():
#     node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
#     node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

#     node_a = RoutedHost(node_a, KademliaPeerRouter(node_a))
#     await node_a.router.listen(5678)
#     node_b = RoutedHost(node_b, KademliaPeerRouter(node_b, [('127.0.0.1', 5678)]))
#     await node_b.router.listen(5679)

#     await node_a.advertise(node_a.get_id().pretty())

#     async def stream_handler(stream):
#         while True:
#             read_string = (await stream.read()).decode()
#             print("host B received:" + read_string)

#             response = "ack:" + read_string
#             print("sending response:" + response)
#             await stream.write(response.encode())

#     node_b.set_stream_handler("/echo/1.0.0", stream_handler)

#     info = info_from_p2p_addr(node_b.get_addrs()[0])
#     info.addrs = []  # explicitly empty the addrs to force the router to look in the dht
#     await node_a.connect(info)

#     stream = await node_a.new_stream(node_b.get_id(), ["/echo/1.0.0"])

#     messages = ["hello" + str(x) for x in range(10)]
#     for message in messages:
#         await stream.write(message.encode())

#         response = (await stream.read()).decode()

#         print("res: " + response)
#         assert response == ("ack:" + message)

#     # Success, terminate pending tasks.
#     return

@pytest.mark.parametrize("nodes_nr", [2])
# @pytest.mark.parametrize("nodes_nr", [(2**i) for i in range(1, 5)])
@pytest.mark.asyncio
async def test_find_peers(nodes_nr):
    nodes = await _make_routed_hosts(nodes_nr, 5678)
    node_a = nodes[0]

    await node_a.advertise("test")

    for node in nodes[1:]:
        peers = await node.find_peers("test")
        assert len(peers) == 1
        assert peers[0].peer_id == node_a.get_id()


async def _make_routed_host(dht_port, bootstrap_nodes=None):
    node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    routed_node = RoutedHost(node, KademliaPeerRouter(node, bootstrap_nodes))
    await routed_node.router.listen(dht_port)
    return routed_node


async def _make_routed_hosts(n, dht_port):
    hosts = []
    bootraps = []
    for _ in range(n):
        hosts.append(await _make_routed_host(dht_port, bootraps))
        bootraps.append(('127.0.0.1', dht_port))
        dht_port += 1
    return hosts

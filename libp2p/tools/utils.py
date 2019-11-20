from typing import List, Sequence, Tuple

import multiaddr

from libp2p import new_node
from libp2p.host.basic_host import BasicHost
from libp2p.host.host_interface import IHost
from libp2p.kademlia.network import KademliaServer
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.network.swarm import Swarm
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.routing.interfaces import IPeerRouting
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter
from libp2p.typing import StreamHandlerFn, TProtocol

from .constants import MAX_READ_LEN


async def connect_swarm(swarm_0: Swarm, swarm_1: Swarm) -> None:
    peer_id = swarm_1.get_peer_id()
    addrs = tuple(
        addr
        for transport in swarm_1.listeners.values()
        for addr in transport.get_addrs()
    )
    swarm_0.peerstore.add_addrs(peer_id, addrs, 10000)
    await swarm_0.dial_peer(peer_id)
    assert swarm_0.get_peer_id() in swarm_1.connections
    assert swarm_1.get_peer_id() in swarm_0.connections


async def connect(node1: IHost, node2: IHost) -> None:
    """Connect node1 to node2."""
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node1.connect(info)


async def set_up_nodes_by_transport_opt(
    transport_opt_list: Sequence[Sequence[str]]
) -> Tuple[BasicHost, ...]:
    nodes_list = []
    for transport_opt in transport_opt_list:
        node = await new_node(transport_opt=transport_opt)
        await node.get_network().listen(multiaddr.Multiaddr(transport_opt[0]))
        nodes_list.append(node)
    return tuple(nodes_list)


async def set_up_nodes_by_transport_and_disc_opt(
    transport_disc_opt_list: Sequence[Tuple[Sequence[str], IPeerRouting]]
) -> Tuple[BasicHost, ...]:
    nodes_list = []
    for transport_opt, disc_opt in transport_disc_opt_list:
        node = await new_node(transport_opt=transport_opt, disc_opt=disc_opt)
        await node.get_network().listen(multiaddr.Multiaddr(transport_opt[0]))
        nodes_list.append(node)
    return tuple(nodes_list)


async def set_up_routers(
    router_confs: Tuple[int, int] = (0, 0)
) -> List[KadmeliaPeerRouter]:
    """The default ``router_confs`` selects two free ports local to this
    machine."""
    bootstrap_node = KademliaServer()  # type: ignore
    await bootstrap_node.listen(router_confs[0])

    routers = [KadmeliaPeerRouter(bootstrap_node)]
    for port in router_confs[1:]:
        node = KademliaServer()  # type: ignore
        await node.listen(port)

        await node.bootstrap_node(bootstrap_node.address)
        routers.append(KadmeliaPeerRouter(node))
    return routers


async def echo_stream_handler(stream: INetStream) -> None:
    while True:
        read_string = (await stream.read(MAX_READ_LEN)).decode()

        resp = "ack:" + read_string
        await stream.write(resp.encode())


async def perform_two_host_set_up(
    handler: StreamHandlerFn = echo_stream_handler
) -> Tuple[BasicHost, BasicHost]:
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    node_b.set_stream_handler(TProtocol("/echo/1.0.0"), handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    return node_a, node_b

from typing import Awaitable, Callable

from libp2p.host.host_interface import IHost
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.network.swarm import Swarm
from libp2p.peer.peerinfo import info_from_p2p_addr

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


def create_echo_stream_handler(
    ack_prefix: str
) -> Callable[[INetStream], Awaitable[None]]:
    async def echo_stream_handler(stream: INetStream) -> None:
        while True:
            read_string = (await stream.read(MAX_READ_LEN)).decode()

            resp = ack_prefix + read_string
            await stream.write(resp.encode())

    return echo_stream_handler

from collections.abc import (
    Awaitable,
)
from typing import (
    Callable,
)

import trio

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.network.stream.exceptions import (
    StreamError,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

from .constants import (
    MAX_READ_LEN,
)


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
    with trio.move_on_after(5):  # 5 second timeout
        await node1.connect(info)
        # Wait a bit to ensure the connection is fully established
        await trio.sleep(0.1)


def create_echo_stream_handler(
    ack_prefix: str,
) -> Callable[[INetStream], Awaitable[None]]:
    async def echo_stream_handler(stream: INetStream) -> None:
        while True:
            try:
                read_string = (await stream.read(MAX_READ_LEN)).decode()
            except StreamError:
                break

            resp = ack_prefix + read_string
            try:
                await stream.write(resp.encode())
            except StreamError:
                break

    return echo_stream_handler

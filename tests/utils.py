import asyncio
from contextlib import suppress

import multiaddr

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from tests.constants import MAX_READ_LEN


async def connect(node1, node2):
    """
    Connect node1 to node2
    """
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node1.connect(info)


# FIXME: Should be deprecated, since it also kills the main task.
async def cleanup():
    pending = asyncio.all_tasks()
    for task in pending:
        task.cancel()

        # Now we should await task to execute it's cancellation.
        # Cancelled task raises asyncio.CancelledError that we can suppress:
        # NOTE: Changed from `asyncio.CancelledError` to `Exception`, to suppress all exceptions
        #   including the one in `run_until_complete`.
        with suppress(Exception):
            await task


async def set_up_nodes_by_transport_opt(transport_opt_list):
    nodes_list = []
    for transport_opt in transport_opt_list:
        node = await new_node(transport_opt=transport_opt)
        await node.get_network().listen(multiaddr.Multiaddr(transport_opt[0]))
        nodes_list.append(node)
    return tuple(nodes_list)


async def echo_stream_handler(stream):
    while True:
        read_string = (await stream.read(MAX_READ_LEN)).decode()

        resp = "ack:" + read_string
        await stream.write(resp.encode())


async def perform_two_host_set_up(handler=echo_stream_handler):
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (node_a, node_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    node_b.set_stream_handler("/echo/1.0.0", handler)

    # Associate the peer with local ip address (see default parameters of Libp2p())
    node_a.get_peerstore().add_addrs(node_b.get_id(), node_b.get_addrs(), 10)
    return node_a, node_b

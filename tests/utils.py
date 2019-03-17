from contextlib import suppress
import asyncio
import multiaddr

from libp2p import new_node


async def cleanup():
    pending = asyncio.all_tasks()
    for task in pending:
        task.cancel()

        # Now we should await task to execute it's cancellation.
        # Cancelled task raises asyncio.CancelledError that we can suppress:
        with suppress(asyncio.CancelledError):
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
        read_string = (await stream.read()).decode()

        resp = "ack:" + read_string
        await stream.write(resp.encode())

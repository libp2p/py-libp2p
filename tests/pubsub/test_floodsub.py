import asyncio
import multiaddr
import pytest

from tests.utils import cleanup
from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from pubsub.pubsub import Pubsub
from pubsub.floodsub import FloodSub

# pylint: disable=too-many-locals

@pytest.mark.asyncio
async def test_simple_two_nodes():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    supported_protocols = ["/floodsub/1.0.0"]

    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, "a")
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b")

    # node_a connects to node_b
    addr = node_b.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node_a.connect(info)

    def callback_a(msg):
        print("a: " + msg)

    def callback_b(msg):
        assert msg == "fuck"

    await asyncio.sleep(0.5)
    qb = await pubsub_b.subscribe("my_topic")

    await asyncio.sleep(0.5)

    node_a_id = str(node_a.get_id())

    msg = "talk\n"
    msg += node_a_id + '\n' + node_a_id + '\n'
    msg += "my_topic" + '\n' + "some message data"

    asyncio.ensure_future(floodsub_a.publish(node_a.get_id(), msg))

    await asyncio.sleep(0.5)

    f = await qb.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert f == msg

    # Success, terminate pending tasks.
    await cleanup()

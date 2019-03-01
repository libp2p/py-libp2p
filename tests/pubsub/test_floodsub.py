import asyncio
import multiaddr
import pytest

from tests.utils import cleanup
from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from pubsub.pubsub import Pubsub
from pubsub.floodsub import FloodSub
from pubsub.message import MessageTalk

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

    await asyncio.sleep(0.25)
    qb = await pubsub_b.subscribe("my_topic")

    await asyncio.sleep(0.25)

    node_a_id = str(node_a.get_id())

    msg = MessageTalk(node_a_id, node_a_id, ["my_topic"], "some data")

    asyncio.ensure_future(floodsub_a.publish(node_a.get_id(), msg.to_str()))

    await asyncio.sleep(0.25)

    res_b = await qb.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert res_b == msg.to_str()

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_simple_three_nodes():
    # Want to pass message from A -> B -> C
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_c = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    supported_protocols = ["/floodsub/1.0.0"]

    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, "a")
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b")
    floodsub_c = FloodSub(supported_protocols)
    pubsub_c = Pubsub(node_c, floodsub_c, "c")

    # node_a connects to node_b
    addr_b = node_b.get_addrs()[0]
    info_b = info_from_p2p_addr(addr_b)
    await node_a.connect(info_b)

    # node_b connects to node_c
    addr_c = node_c.get_addrs()[0]
    info_c = info_from_p2p_addr(addr_c)
    await node_b.connect(info_c)

    await asyncio.sleep(0.25)
    qb = await pubsub_b.subscribe("my_topic")
    qc = await pubsub_c.subscribe("my_topic")
    await asyncio.sleep(0.25)

    node_a_id = str(node_a.get_id())

    msg = MessageTalk(node_a_id, node_a_id, ["my_topic"], "some data")

    asyncio.ensure_future(floodsub_a.publish(node_a.get_id(), msg.to_str()))
    await asyncio.sleep(0.25)

    res_b = await qb.get()
    res_c = await qc.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert res_b == msg.to_str()

    # res_c should match original msg but with b as sender
    node_b_id = str(node_b.get_id())
    msg.from_id = node_b_id

    assert res_c == msg.to_str()

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_simple_three_nodes():
    # Want to pass message from A -> B -> C
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_c = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    supported_protocols = ["/floodsub/1.0.0"]

    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, "a")
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b")
    floodsub_c = FloodSub(supported_protocols)
    pubsub_c = Pubsub(node_c, floodsub_c, "c")

    # node_a connects to node_b
    addr_b = node_b.get_addrs()[0]
    info_b = info_from_p2p_addr(addr_b)
    await node_a.connect(info_b)

    # node_b connects to node_c
    addr_c = node_c.get_addrs()[0]
    info_c = info_from_p2p_addr(addr_c)
    await node_b.connect(info_c)

    await asyncio.sleep(0.25)
    qb = await pubsub_b.subscribe("my_topic")
    qc = await pubsub_c.subscribe("my_topic")
    await asyncio.sleep(0.25)

    node_a_id = str(node_a.get_id())

    msg = MessageTalk(node_a_id, node_a_id, ["my_topic"], "some data")

    asyncio.ensure_future(floodsub_a.publish(node_a.get_id(), msg.to_str()))
    await asyncio.sleep(0.25)

    res_b = await qb.get()
    res_c = await qc.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert res_b == msg.to_str()

    # res_c should match original msg but with b as sender
    node_b_id = str(node_b.get_id())
    msg.from_id = node_b_id

    assert res_c == msg.to_str()

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_three_nodes_two_topics():
    # Want to pass two messages from A -> B -> C on two topics
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_c = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    supported_protocols = ["/floodsub/1.0.0"]

    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, "a")
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b")
    floodsub_c = FloodSub(supported_protocols)
    pubsub_c = Pubsub(node_c, floodsub_c, "c")

    # node_a connects to node_b
    addr_b = node_b.get_addrs()[0]
    info_b = info_from_p2p_addr(addr_b)
    await node_a.connect(info_b)

    # node_b connects to node_c
    addr_c = node_c.get_addrs()[0]
    info_c = info_from_p2p_addr(addr_c)
    await node_b.connect(info_c)

    await asyncio.sleep(0.25)
    qb_t1 = await pubsub_b.subscribe("t1")
    qc_t1 = await pubsub_c.subscribe("t1")
    qb_t2 = await pubsub_b.subscribe("t2")
    qc_t2 = await pubsub_c.subscribe("t2")
    await asyncio.sleep(0.25)

    node_a_id = str(node_a.get_id())

    msg_t1 = MessageTalk(node_a_id, node_a_id, ["t1"], "some data")
    asyncio.ensure_future(floodsub_a.publish(node_a.get_id(), msg_t1.to_str()))

    msg_t2 = MessageTalk(node_a_id, node_a_id, ["t2"], "some data")
    asyncio.ensure_future(floodsub_a.publish(node_a.get_id(), msg_t2.to_str()))

    await asyncio.sleep(0.25)

    res_b_t1 = await qb_t1.get()
    res_c_t1 = await qc_t1.get()
    res_b_t2 = await qb_t2.get()
    res_c_t2 = await qc_t2.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert res_b_t1 == msg_t1.to_str()
    assert res_b_t2 == msg_t2.to_str()

    # res_c should match original msg but with b as sender
    node_b_id = str(node_b.get_id())
    msg_t1.from_id = node_b_id
    msg_t2.from_id = node_b_id

    assert res_c_t1 == msg_t1.to_str()
    assert res_c_t2 == msg_t2.to_str()

    # Success, terminate pending tasks.
    await cleanup()
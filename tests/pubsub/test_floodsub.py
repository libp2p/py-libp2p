import asyncio
import multiaddr
import pytest

from tests.utils import cleanup
from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from pubsub.pubsub import Pubsub
from pubsub.floodsub import FloodSub
from pubsub.message import MessageTalk
from pubsub.message import create_message_talk

# pylint: disable=too-many-locals

async def connect(node1, node2):
    # node1 connects to node2
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node1.connect(info)

@pytest.mark.asyncio
async def test_simple_two_nodes():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    supported_protocols = ["/floodsub/1.0.0"]

    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, "a")
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b")

    await connect(node_a, node_b)

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

    await connect(node_a, node_b)
    await connect(node_b, node_c)

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

    await connect(node_a, node_b)
    await connect(node_b, node_c)

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

async def perform_test_from_obj(obj):
    # Step 1) Create graph
    adj_list = obj["adj_list"]
    node_map = {}
    floodsub_map = {}
    pubsub_map = {}

    supported_protocols = obj["supported_protocols"]

    for start_node_id in adj_list:
        # Create node if node does not yet exist
        if start_node_id not in node_map:
            node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
            node_map[start_node_id] = node

            floodsub = FloodSub(supported_protocols)
            floodsub_map[start_node_id] = floodsub
            pubsub = Pubsub(node, floodsub, start_node_id)
            pubsub_map[start_node_id] = pubsub

        # For each neighbor of start_node, create if does not yet exist,
        # then connect start_node to neighbor
        for neighbor_id in adj_list[start_node_id]:
            # Create neighbor if neighbor does not yet exist
            if neighbor_id not in node_map:
                neighbor_node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
                node_map[neighbor_id] = neighbor_node

                floodsub = FloodSub(supported_protocols)
                floodsub_map[neighbor_id] = floodsub
                pubsub = Pubsub(neighbor_node, floodsub, neighbor_id)
                pubsub_map[neighbor_id] = pubsub

            # Connect node and neighbor
            await connect(node_map[start_node_id], node_map[neighbor_id])

    # Allow time for graph creation before continuing
    await asyncio.sleep(0.25)

    # Step 2) Subscribe to topics
    queues_map = {}
    topic_map = obj["topic_map"]

    for topic in topic_map:
        for node_id in topic_map[topic]:
            # Subscribe node to topic
            q = await pubsub_map[node_id].subscribe(topic)

            # Create topic-queue map for node_id if one does not yet exist
            if node_id not in queues_map:
                queues_map[node_id] = {}

            # Store queue in topic-queue map for node
            queues_map[node_id][topic] = q

    # Allow time for subscribing before continuing
    await asyncio.sleep(0.25)

    # Step 3) Publish messages
    topics_in_msgs_ordered = []
    messages = obj["messages"]
    loop = asyncio.get_event_loop()
    for msg in messages:
        topics = msg["topics"]

        data = msg["data"]
        node_id = msg["node_id"]

        # Get actual id for node (not the id from the test obj)
        actual_node_id = str(node_map[node_id].get_id())

        # Create correctly formatted message
        msg_talk = MessageTalk(actual_node_id, actual_node_id, topics, data)
        
        # Publish message
        asyncio.ensure_future(floodsub_map[node_id].publish(actual_node_id, msg_talk.to_str()))

        # For each topic in topics, add topic, msg_talk tuple to ordered test list
        # TODO: Update message sender to be correct message sender before
        # adding msg_talk to this list
        for topic in topics:
            topics_in_msgs_ordered.append((topic, msg_talk))

    # Allow time for publishing before continuing
    await asyncio.sleep(0.25)

    # Step 4) Check that all messages were received correctly.
    # TODO: Check message sender too
    for i in range(len(topics_in_msgs_ordered)):
        topic, actual_msg = topics_in_msgs_ordered[i]
        for node_id in topic_map[topic]:
            # Get message from subscription queue
            msg_on_node_str = await queues_map[node_id][topic].get()
            msg_on_node = create_message_talk(msg_on_node_str)

            # Perform checks
            assert actual_msg.origin_id == msg_on_node.origin_id
            assert actual_msg.topics == msg_on_node.topics
            assert actual_msg.data == msg_on_node.data

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_simple_two_nodes_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {
            "A": ["B"]
        },
        "topic_map": {
            "topic1": ["B"]
        },
        "messages": [
            {
                "topics": ["topic1"],
                "data": "foo",
                "node_id": "A"
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_three_nodes_two_topics_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {
            "A": ["B"],
            "B": ["C"]
        },
        "topic_map": {
            "topic1": ["B", "C"],
            "topic2": ["B", "C"]
        },
        "messages": [
            {
                "topics": ["topic1"],
                "data": "foo",
                "node_id": "A"
            },
            {
                "topics": ["topic2"],
                "data": "Alex is tall",
                "node_id": "A"
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_seven_nodes_tree_one_topics_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {
            "1": ["2", "3"],
            "2": ["4", "5"],
            "3": ["6", "7"]
        },
        "topic_map": {
            "astrophysics": ["2", "3", "4", "5", "6", "7"]
        },
        "messages": [
            {
                "topics": ["astrophysics"],
                "data": "e=mc^2",
                "node_id": "1"
            }
        ]
    }
    await perform_test_from_obj(test_obj)
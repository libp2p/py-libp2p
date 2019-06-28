import asyncio

import multiaddr
import pytest
from utils import generate_RPC_packet, message_id_generator

from libp2p import new_node
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub
from tests.utils import cleanup


async def connect(node1, node2):
    """
    Connect node1 to node2
    """
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node1.connect(info)


@pytest.mark.asyncio
async def test_simple_two_nodes():
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    await node_a.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))
    await node_b.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))

    supported_protocols = ["/floodsub/1.0.0"]

    floodsub_a = FloodSub(supported_protocols)
    _ = Pubsub(node_a, floodsub_a, "a")
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b")

    await connect(node_a, node_b)

    await asyncio.sleep(0.25)
    qb = await pubsub_b.subscribe("my_topic")

    await asyncio.sleep(0.25)

    node_a_id = str(node_a.get_id())

    next_msg_id_func = message_id_generator(0)
    msg = generate_RPC_packet(node_a_id, ["my_topic"], "some data", next_msg_id_func())
    await floodsub_a.publish(node_a_id, msg.SerializeToString())
    await asyncio.sleep(0.25)

    res_b = await qb.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert res_b.SerializeToString() == msg.publish[0].SerializeToString()

    # Success, terminate pending tasks.
    await cleanup()


@pytest.mark.asyncio
async def test_lru_cache_two_nodes():
    # two nodes with cache_size of 4
    # node_a send the following messages to node_b
    # [1, 1, 2, 1, 3, 1, 4, 1, 5, 1]
    # node_b should only receive the following
    # [1, 2, 3, 4, 5, 1]
    node_a = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    node_b = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    await node_a.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))
    await node_b.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))

    supported_protocols = ["/floodsub/1.0.0"]

    # initialize PubSub with a cache_size of 4
    floodsub_a = FloodSub(supported_protocols)
    _ = Pubsub(node_a, floodsub_a, "a", 4)
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, "b", 4)

    await connect(node_a, node_b)

    await asyncio.sleep(0.25)
    qb = await pubsub_b.subscribe("my_topic")

    await asyncio.sleep(0.25)

    node_a_id = str(node_a.get_id())

    # initialize message_id_generator
    # store first message
    next_msg_id_func = message_id_generator(0)
    first_message = generate_RPC_packet(
        node_a_id, ["my_topic"], "some data 1", next_msg_id_func()
    )

    await floodsub_a.publish(node_a_id, first_message.SerializeToString())
    await asyncio.sleep(0.25)
    print(first_message)

    messages = [first_message]
    # for the next 5 messages
    for i in range(2, 6):
        # write first message
        await floodsub_a.publish(node_a_id, first_message.SerializeToString())
        await asyncio.sleep(0.25)

        # generate and write next message
        msg = generate_RPC_packet(
            node_a_id, ["my_topic"], "some data " + str(i), next_msg_id_func()
        )
        messages.append(msg)

        await floodsub_a.publish(node_a_id, msg.SerializeToString())
        await asyncio.sleep(0.25)

    # write first message again
    await floodsub_a.publish(node_a_id, first_message.SerializeToString())
    await asyncio.sleep(0.25)

    # check the first five messages in queue
    # should only see 1 first_message
    for i in range(5):
        # Check that the msg received by node_b is the same
        # as the message sent by node_a
        res_b = await qb.get()
        assert res_b.SerializeToString() == messages[i].publish[0].SerializeToString()

    # the 6th message should be first_message
    res_b = await qb.get()
    assert res_b.SerializeToString() == first_message.publish[0].SerializeToString()
    assert qb.empty()

    # Success, terminate pending tasks.
    await cleanup()


async def perform_test_from_obj(obj):
    """
    Perform a floodsub test from a test obj.
    test obj are composed as follows:

    {
        "supported_protocols": ["supported/protocol/1.0.0",...],
        "adj_list": {
            "node1": ["neighbor1_of_node1", "neighbor2_of_node1", ...],
            "node2": ["neighbor1_of_node2", "neighbor2_of_node2", ...],
            ...
        },
        "topic_map": {
            "topic1": ["node1_subscribed_to_topic1", "node2_subscribed_to_topic1", ...]
        },
        "messages": [
            {
                "topics": ["topic1_for_message", "topic2_for_message", ...],
                "data": "some contents of the message (newlines are not supported)",
                "node_id": "message sender node id"
            },
            ...
        ]
    }
    NOTE: In adj_list, for any neighbors A and B, only list B as a neighbor of A
    or B as a neighbor of A once. Do NOT list both A: ["B"] and B:["A"] as the behavior
    is undefined (even if it may work)
    """

    # Step 1) Create graph
    adj_list = obj["adj_list"]
    node_map = {}
    floodsub_map = {}
    pubsub_map = {}

    supported_protocols = obj["supported_protocols"]

    tasks_connect = []
    for start_node_id in adj_list:
        # Create node if node does not yet exist
        if start_node_id not in node_map:
            node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
            await node.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))

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
                await neighbor_node.get_network().listen(
                    multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
                )

                node_map[neighbor_id] = neighbor_node

                floodsub = FloodSub(supported_protocols)
                floodsub_map[neighbor_id] = floodsub
                pubsub = Pubsub(neighbor_node, floodsub, neighbor_id)
                pubsub_map[neighbor_id] = pubsub

            # Connect node and neighbor
            # await connect(node_map[start_node_id], node_map[neighbor_id])
            tasks_connect.append(
                asyncio.ensure_future(
                    connect(node_map[start_node_id], node_map[neighbor_id])
                )
            )
    tasks_connect.append(asyncio.sleep(2))
    await asyncio.gather(*tasks_connect)

    # Allow time for graph creation before continuing
    # await asyncio.sleep(0.25)

    # Step 2) Subscribe to topics
    queues_map = {}
    topic_map = obj["topic_map"]

    tasks_topic = []
    tasks_topic_data = []
    for topic in topic_map:
        for node_id in topic_map[topic]:
            """
            # Subscribe node to topic
            q = await pubsub_map[node_id].subscribe(topic)

            # Create topic-queue map for node_id if one does not yet exist
            if node_id not in queues_map:
                queues_map[node_id] = {}

            # Store queue in topic-queue map for node
            queues_map[node_id][topic] = q
            """
            tasks_topic.append(
                asyncio.ensure_future(pubsub_map[node_id].subscribe(topic))
            )
            tasks_topic_data.append((node_id, topic))
    tasks_topic.append(asyncio.sleep(2))

    # Gather is like Promise.all
    responses = await asyncio.gather(*tasks_topic, return_exceptions=True)
    for i in range(len(responses) - 1):
        q = responses[i]
        node_id, topic = tasks_topic_data[i]
        if node_id not in queues_map:
            queues_map[node_id] = {}

        # Store queue in topic-queue map for node
        queues_map[node_id][topic] = q

    # Allow time for subscribing before continuing
    # await asyncio.sleep(0.01)

    # Step 3) Publish messages
    topics_in_msgs_ordered = []
    messages = obj["messages"]
    tasks_publish = []
    next_msg_id_func = message_id_generator(0)

    for msg in messages:
        topics = msg["topics"]

        data = msg["data"]
        node_id = msg["node_id"]

        # Get actual id for sender node (not the id from the test obj)
        actual_node_id = str(node_map[node_id].get_id())

        # Create correctly formatted message
        msg_talk = generate_RPC_packet(actual_node_id, topics, data, next_msg_id_func())

        # Publish message
        # await floodsub_map[node_id].publish(actual_node_id, msg_talk.to_str())
        tasks_publish.append(
            asyncio.ensure_future(
                floodsub_map[node_id].publish(
                    actual_node_id, msg_talk.SerializeToString()
                )
            )
        )

        # For each topic in topics, add topic, msg_talk tuple to ordered test list
        # TODO: Update message sender to be correct message sender before
        # adding msg_talk to this list
        for topic in topics:
            topics_in_msgs_ordered.append((topic, msg_talk))

    # Allow time for publishing before continuing
    # await asyncio.sleep(0.4)
    tasks_publish.append(asyncio.sleep(2))
    await asyncio.gather(*tasks_publish)

    # Step 4) Check that all messages were received correctly.
    # TODO: Check message sender too
    for i in range(len(topics_in_msgs_ordered)):
        topic, actual_msg = topics_in_msgs_ordered[i]

        # Look at each node in each topic
        for node_id in topic_map[topic]:
            # Get message from subscription queue
            msg_on_node_str = await queues_map[node_id][topic].get()
            assert (
                actual_msg.publish[0].SerializeToString()
                == msg_on_node_str.SerializeToString()
            )

    # Success, terminate pending tasks.
    await cleanup()


@pytest.mark.asyncio
async def test_simple_two_nodes_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"A": ["B"]},
        "topic_map": {"topic1": ["B"]},
        "messages": [{"topics": ["topic1"], "data": "foo", "node_id": "A"}],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_three_nodes_two_topics_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"A": ["B"], "B": ["C"]},
        "topic_map": {"topic1": ["B", "C"], "topic2": ["B", "C"]},
        "messages": [
            {"topics": ["topic1"], "data": "foo", "node_id": "A"},
            {"topics": ["topic2"], "data": "Alex is tall", "node_id": "A"},
        ],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_two_nodes_one_topic_single_subscriber_is_sender_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"A": ["B"]},
        "topic_map": {"topic1": ["B"]},
        "messages": [{"topics": ["topic1"], "data": "Alex is tall", "node_id": "B"}],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_two_nodes_one_topic_two_msgs_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"A": ["B"]},
        "topic_map": {"topic1": ["B"]},
        "messages": [
            {"topics": ["topic1"], "data": "Alex is tall", "node_id": "B"},
            {"topics": ["topic1"], "data": "foo", "node_id": "A"},
        ],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_seven_nodes_tree_one_topics_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"1": ["2", "3"], "2": ["4", "5"], "3": ["6", "7"]},
        "topic_map": {"astrophysics": ["2", "3", "4", "5", "6", "7"]},
        "messages": [{"topics": ["astrophysics"], "data": "e=mc^2", "node_id": "1"}],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_seven_nodes_tree_three_topics_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"1": ["2", "3"], "2": ["4", "5"], "3": ["6", "7"]},
        "topic_map": {
            "astrophysics": ["2", "3", "4", "5", "6", "7"],
            "space": ["2", "3", "4", "5", "6", "7"],
            "onions": ["2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": "e=mc^2", "node_id": "1"},
            {"topics": ["space"], "data": "foobar", "node_id": "1"},
            {"topics": ["onions"], "data": "I am allergic", "node_id": "1"},
        ],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_seven_nodes_tree_three_topics_diff_origin_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"1": ["2", "3"], "2": ["4", "5"], "3": ["6", "7"]},
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4", "5", "6", "7"],
            "space": ["1", "2", "3", "4", "5", "6", "7"],
            "onions": ["1", "2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": "e=mc^2", "node_id": "1"},
            {"topics": ["space"], "data": "foobar", "node_id": "4"},
            {"topics": ["onions"], "data": "I am allergic", "node_id": "7"},
        ],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_three_nodes_clique_two_topic_diff_origin_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"1": ["2", "3"], "2": ["3"]},
        "topic_map": {"astrophysics": ["1", "2", "3"], "school": ["1", "2", "3"]},
        "messages": [
            {"topics": ["astrophysics"], "data": "e=mc^2", "node_id": "1"},
            {"topics": ["school"], "data": "foobar", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic", "node_id": "1"},
        ],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_four_nodes_clique_two_topic_diff_origin_many_msgs_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {
            "1": ["2", "3", "4"],
            "2": ["1", "3", "4"],
            "3": ["1", "2", "4"],
            "4": ["1", "2", "3"],
        },
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4"],
            "school": ["1", "2", "3", "4"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": "e=mc^2", "node_id": "1"},
            {"topics": ["school"], "data": "foobar", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic", "node_id": "1"},
            {"topics": ["school"], "data": "foobar2", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic2", "node_id": "1"},
            {"topics": ["school"], "data": "foobar3", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic3", "node_id": "1"},
        ],
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_five_nodes_ring_two_topic_diff_origin_many_msgs_test_obj():
    test_obj = {
        "supported_protocols": ["/floodsub/1.0.0"],
        "adj_list": {"1": ["2"], "2": ["3"], "3": ["4"], "4": ["5"], "5": ["1"]},
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4", "5"],
            "school": ["1", "2", "3", "4", "5"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": "e=mc^2", "node_id": "1"},
            {"topics": ["school"], "data": "foobar", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic", "node_id": "1"},
            {"topics": ["school"], "data": "foobar2", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic2", "node_id": "1"},
            {"topics": ["school"], "data": "foobar3", "node_id": "2"},
            {"topics": ["astrophysics"], "data": "I am allergic3", "node_id": "1"},
        ],
    }
    await perform_test_from_obj(test_obj)

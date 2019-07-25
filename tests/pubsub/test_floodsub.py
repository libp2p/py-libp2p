import asyncio
import multiaddr
import pytest

from libp2p import new_node
from libp2p.peer.id import ID
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.floodsub import FloodSub

from tests.utils import (
    cleanup,
    connect,
)
from .utils import (
    message_id_generator,
    generate_RPC_packet,
)


# pylint: disable=too-many-locals
FLOODSUB_PROTOCOL_ID = "/floodsub/1.0.0"
SUPPORTED_PROTOCOLS = [FLOODSUB_PROTOCOL_ID]

LISTEN_MADDR = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")


@pytest.mark.asyncio
async def test_simple_two_nodes():
    node_a = await new_node(transport_opt=[str(LISTEN_MADDR)])
    node_b = await new_node(transport_opt=[str(LISTEN_MADDR)])

    await node_a.get_network().listen(LISTEN_MADDR)
    await node_b.get_network().listen(LISTEN_MADDR)

    supported_protocols = [FLOODSUB_PROTOCOL_ID]
    topic = "my_topic"
    data = b"some data"

    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, ID(b"a" * 32))
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, ID(b"b" * 32))

    await connect(node_a, node_b)
    await asyncio.sleep(0.25)

    sub_b = await pubsub_b.subscribe(topic)
    # Sleep to let a know of b's subscription
    await asyncio.sleep(0.25)

    await pubsub_a.publish(topic, data)

    res_b = await sub_b.get()

    # Check that the msg received by node_b is the same
    # as the message sent by node_a
    assert ID(res_b.from_id) == node_a.get_id()
    assert res_b.data == data
    assert res_b.topicIDs == [topic]

    # Success, terminate pending tasks.
    await cleanup()


@pytest.mark.asyncio
async def test_lru_cache_two_nodes(monkeypatch):
    # two nodes with cache_size of 4
    # `node_a` send the following messages to node_b
    message_indices = [1, 1, 2, 1, 3, 1, 4, 1, 5, 1]
    # `node_b` should only receive the following
    expected_received_indices = [1, 2, 3, 4, 5, 1]

    node_a = await new_node(transport_opt=[str(LISTEN_MADDR)])
    node_b = await new_node(transport_opt=[str(LISTEN_MADDR)])

    await node_a.get_network().listen(LISTEN_MADDR)
    await node_b.get_network().listen(LISTEN_MADDR)

    supported_protocols = SUPPORTED_PROTOCOLS
    topic = "my_topic"

    # Mock `get_msg_id` to make us easier to manipulate `msg_id` by `data`.
    def get_msg_id(msg):
        # Originally it is `(msg.seqno, msg.from_id)`
        return (msg.data, msg.from_id)
    import libp2p.pubsub.pubsub
    monkeypatch.setattr(libp2p.pubsub.pubsub, "get_msg_id", get_msg_id)

    # Initialize Pubsub with a cache_size of 4
    cache_size = 4
    floodsub_a = FloodSub(supported_protocols)
    pubsub_a = Pubsub(node_a, floodsub_a, ID(b"a" * 32), cache_size)

    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, ID(b"b" * 32), cache_size)

    await connect(node_a, node_b)
    await asyncio.sleep(0.25)

    sub_b = await pubsub_b.subscribe(topic)
    await asyncio.sleep(0.25)

    def _make_testing_data(i: int) -> bytes:
        num_int_bytes = 4
        if i >= 2**(num_int_bytes * 8):
            raise ValueError("integer is too large to be serialized")
        return b"data" + i.to_bytes(num_int_bytes, "big")

    for index in message_indices:
        await pubsub_a.publish(topic, _make_testing_data(index))
    await asyncio.sleep(0.25)

    for index in expected_received_indices:
        res_b = await sub_b.get()
        assert res_b.data == _make_testing_data(index)
    assert sub_b.empty()

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
                "data": b"some contents of the message (newlines are not supported)",
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

    async def add_node(node_id: str) -> None:
        node = await new_node(transport_opt=[str(LISTEN_MADDR)])
        await node.get_network().listen(LISTEN_MADDR)
        node_map[node_id] = node
        floodsub = FloodSub(supported_protocols)
        floodsub_map[node_id] = floodsub
        pubsub = Pubsub(node, floodsub, ID(node_id.encode()))
        pubsub_map[node_id] = pubsub

    supported_protocols = obj["supported_protocols"]

    tasks_connect = []
    for start_node_id in adj_list:
        # Create node if node does not yet exist
        if start_node_id not in node_map:
            await add_node(start_node_id)

        # For each neighbor of start_node, create if does not yet exist,
        # then connect start_node to neighbor
        for neighbor_id in adj_list[start_node_id]:
            # Create neighbor if neighbor does not yet exist
            if neighbor_id not in node_map:
                await add_node(neighbor_id)
            tasks_connect.append(
                connect(node_map[start_node_id], node_map[neighbor_id])
            )
    # Connect nodes and wait at least for 2 seconds
    await asyncio.gather(*tasks_connect, asyncio.sleep(2))

    # Step 2) Subscribe to topics
    queues_map = {}
    topic_map = obj["topic_map"]

    tasks_topic = []
    tasks_topic_data = []
    for topic, node_ids in topic_map.items():
        for node_id in node_ids:
            tasks_topic.append(pubsub_map[node_id].subscribe(topic))
            tasks_topic_data.append((node_id, topic))
    tasks_topic.append(asyncio.sleep(2))

    # Gather is like Promise.all
    responses = await asyncio.gather(*tasks_topic, return_exceptions=True)
    for i in range(len(responses) - 1):
        node_id, topic = tasks_topic_data[i]
        if node_id not in queues_map:
            queues_map[node_id] = {}
        # Store queue in topic-queue map for node
        queues_map[node_id][topic] = responses[i]

    # Allow time for subscribing before continuing
    await asyncio.sleep(0.01)

    # Step 3) Publish messages
    topics_in_msgs_ordered = []
    messages = obj["messages"]
    tasks_publish = []

    for msg in messages:
        topics = msg["topics"]
        data = msg["data"]
        node_id = msg["node_id"]

        # Publish message
        # FIXME: Should be single RPC package with several topics
        for topic in topics:
            tasks_publish.append(
                pubsub_map[node_id].publish(
                    topic,
                    data,
                )
            )

        # For each topic in topics, add topic, msg_talk tuple to ordered test list
        # TODO: Update message sender to be correct message sender before
        # adding msg_talk to this list
        for topic in topics:
            topics_in_msgs_ordered.append((topic, data))

    # Allow time for publishing before continuing
    await asyncio.gather(*tasks_publish, asyncio.sleep(2))

    # Step 4) Check that all messages were received correctly.
    # TODO: Check message sender too
    for topic, data in topics_in_msgs_ordered:
        # Look at each node in each topic
        for node_id in topic_map[topic]:
            # Get message from subscription queue
            msg = await queues_map[node_id][topic].get()
            assert data == msg.data

    # Success, terminate pending tasks.
    await cleanup()


@pytest.mark.asyncio
async def test_simple_two_nodes_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "A": ["B"]
        },
        "topic_map": {
            "topic1": ["B"]
        },
        "messages": [
            {
                "topics": ["topic1"],
                "data": b"foo",
                "node_id": "A"
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_three_nodes_two_topics_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "A": ["B"],
            "B": ["C"],
        },
        "topic_map": {
            "topic1": ["B", "C"],
            "topic2": ["B", "C"],
        },
        "messages": [
            {
                "topics": ["topic1"],
                "data": b"foo",
                "node_id": "A",
            },
            {
                "topics": ["topic2"],
                "data": b"Alex is tall",
                "node_id": "A",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_two_nodes_one_topic_single_subscriber_is_sender_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "A": ["B"],
        },
        "topic_map": {
            "topic1": ["B"],
        },
        "messages": [
            {
                "topics": ["topic1"],
                "data": b"Alex is tall",
                "node_id": "B",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_two_nodes_one_topic_two_msgs_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "A": ["B"],
        },
        "topic_map": {
            "topic1": ["B"],
        },
        "messages": [
            {
                "topics": ["topic1"],
                "data": b"Alex is tall",
                "node_id": "B",
            },
            {
                "topics": ["topic1"],
                "data": b"foo",
                "node_id": "A",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_seven_nodes_tree_one_topics_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "1": ["2", "3"],
            "2": ["4", "5"],
            "3": ["6", "7"],
        },
        "topic_map": {
            "astrophysics": ["2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {
                "topics": ["astrophysics"],
                "data": b"e=mc^2",
                "node_id": "1",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_seven_nodes_tree_three_topics_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "1": ["2", "3"],
            "2": ["4", "5"],
            "3": ["6", "7"],
        },
        "topic_map": {
            "astrophysics": ["2", "3", "4", "5", "6", "7"],
            "space": ["2", "3", "4", "5", "6", "7"],
            "onions": ["2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {
                "topics": ["astrophysics"],
                "data": b"e=mc^2",
                "node_id": "1",
            },
            {
                "topics": ["space"],
                "data": b"foobar",
                "node_id": "1",
            },
            {
                "topics": ["onions"],
                "data": b"I am allergic",
                "node_id": "1",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_seven_nodes_tree_three_topics_diff_origin_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "1": ["2", "3"],
            "2": ["4", "5"],
            "3": ["6", "7"],
        },
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4", "5", "6", "7"],
            "space": ["1", "2", "3", "4", "5", "6", "7"],
            "onions": ["1", "2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {
                "topics": ["astrophysics"],
                "data": b"e=mc^2",
                "node_id": "1",
            },
            {
                "topics": ["space"],
                "data": b"foobar",
                "node_id": "4",
            },
            {
                "topics": ["onions"],
                "data": b"I am allergic",
                "node_id": "7",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

@pytest.mark.asyncio
async def test_three_nodes_clique_two_topic_diff_origin_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "1": ["2", "3"],
            "2": ["3"],
        },
        "topic_map": {
            "astrophysics": ["1", "2", "3"],
            "school": ["1", "2", "3"],
        },
        "messages": [
            {
                "topics": ["astrophysics"],
                "data": b"e=mc^2",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic",
                "node_id": "1",
            }
        ]
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_four_nodes_clique_two_topic_diff_origin_many_msgs_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
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
            {
                "topics": ["astrophysics"],
                "data": b"e=mc^2",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar2",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic2",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar3",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic3",
                "node_id": "1",
            }
        ]
    }
    await perform_test_from_obj(test_obj)


@pytest.mark.asyncio
async def test_five_nodes_ring_two_topic_diff_origin_many_msgs_test_obj():
    test_obj = {
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "adj_list": {
            "1": ["2"],
            "2": ["3"],
            "3": ["4"],
            "4": ["5"],
            "5": ["1"],
        },
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4", "5"],
            "school": ["1", "2", "3", "4", "5"],
        },
        "messages": [
            {
                "topics": ["astrophysics"],
                "data": b"e=mc^2",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar2",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic2",
                "node_id": "1",
            },
            {
                "topics": ["school"],
                "data": b"foobar3",
                "node_id": "2",
            },
            {
                "topics": ["astrophysics"],
                "data": b"I am allergic3",
                "node_id": "1",
            }
        ]
    }
    await perform_test_from_obj(test_obj)

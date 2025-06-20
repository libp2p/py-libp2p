import pytest
import trio

from libp2p.tools.constants import (
    FLOODSUB_PROTOCOL_ID,
)
from libp2p.tools.utils import (
    connect,
)

SUPPORTED_PROTOCOLS = [FLOODSUB_PROTOCOL_ID]

FLOODSUB_PROTOCOL_TEST_CASES = [
    {
        "name": "simple_two_nodes",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["A", "B"],
        "adj_list": {"A": ["B"]},
        "topic_map": {"topic1": ["B"]},
        "messages": [{"topics": ["topic1"], "data": b"foo", "node_id": "A"}],
    },
    {
        "name": "three_nodes_two_topics",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["A", "B", "C"],
        "adj_list": {"A": ["B"], "B": ["C"]},
        "topic_map": {"topic1": ["B", "C"], "topic2": ["B", "C"]},
        "messages": [
            {"topics": ["topic1"], "data": b"foo", "node_id": "A"},
            {"topics": ["topic2"], "data": b"Alex is tall", "node_id": "A"},
        ],
    },
    {
        "name": "two_nodes_one_topic_single_subscriber_is_sender",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["A", "B"],
        "adj_list": {"A": ["B"]},
        "topic_map": {"topic1": ["B"]},
        "messages": [{"topics": ["topic1"], "data": b"Alex is tall", "node_id": "B"}],
    },
    {
        "name": "two_nodes_one_topic_two_msgs",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["A", "B"],
        "adj_list": {"A": ["B"]},
        "topic_map": {"topic1": ["B"]},
        "messages": [
            {"topics": ["topic1"], "data": b"Alex is tall", "node_id": "B"},
            {"topics": ["topic1"], "data": b"foo", "node_id": "A"},
        ],
    },
    {
        "name": "seven_nodes_tree_one_topics",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["1", "2", "3", "4", "5", "6", "7"],
        "adj_list": {"1": ["2", "3"], "2": ["4", "5"], "3": ["6", "7"]},
        "topic_map": {"astrophysics": ["2", "3", "4", "5", "6", "7"]},
        "messages": [{"topics": ["astrophysics"], "data": b"e=mc^2", "node_id": "1"}],
    },
    {
        "name": "seven_nodes_tree_three_topics",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["1", "2", "3", "4", "5", "6", "7"],
        "adj_list": {"1": ["2", "3"], "2": ["4", "5"], "3": ["6", "7"]},
        "topic_map": {
            "astrophysics": ["2", "3", "4", "5", "6", "7"],
            "space": ["2", "3", "4", "5", "6", "7"],
            "onions": ["2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": b"e=mc^2", "node_id": "1"},
            {"topics": ["space"], "data": b"foobar", "node_id": "1"},
            {"topics": ["onions"], "data": b"I am allergic", "node_id": "1"},
        ],
    },
    {
        "name": "seven_nodes_tree_three_topics_diff_origin",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["1", "2", "3", "4", "5", "6", "7"],
        "adj_list": {"1": ["2", "3"], "2": ["4", "5"], "3": ["6", "7"]},
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4", "5", "6", "7"],
            "space": ["1", "2", "3", "4", "5", "6", "7"],
            "onions": ["1", "2", "3", "4", "5", "6", "7"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": b"e=mc^2", "node_id": "1"},
            {"topics": ["space"], "data": b"foobar", "node_id": "4"},
            {"topics": ["onions"], "data": b"I am allergic", "node_id": "7"},
        ],
    },
    {
        "name": "three_nodes_clique_two_topic_diff_origin",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["1", "2", "3"],
        "adj_list": {"1": ["2", "3"], "2": ["3"]},
        "topic_map": {"astrophysics": ["1", "2", "3"], "school": ["1", "2", "3"]},
        "messages": [
            {"topics": ["astrophysics"], "data": b"e=mc^2", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic", "node_id": "1"},
        ],
    },
    {
        "name": "four_nodes_clique_two_topic_diff_origin_many_msgs",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["1", "2", "3", "4"],
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
            {"topics": ["astrophysics"], "data": b"e=mc^2", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar2", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic2", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar3", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic3", "node_id": "1"},
        ],
    },
    {
        "name": "five_nodes_ring_two_topic_diff_origin_many_msgs",
        "supported_protocols": SUPPORTED_PROTOCOLS,
        "nodes": ["1", "2", "3", "4", "5"],
        "adj_list": {"1": ["2"], "2": ["3"], "3": ["4"], "4": ["5"], "5": ["1"]},
        "topic_map": {
            "astrophysics": ["1", "2", "3", "4", "5"],
            "school": ["1", "2", "3", "4", "5"],
        },
        "messages": [
            {"topics": ["astrophysics"], "data": b"e=mc^2", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar2", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic2", "node_id": "1"},
            {"topics": ["school"], "data": b"foobar3", "node_id": "2"},
            {"topics": ["astrophysics"], "data": b"I am allergic3", "node_id": "1"},
        ],
    },
]

floodsub_protocol_pytest_params = [
    pytest.param(test_case, id=str(test_case["name"]))
    for test_case in FLOODSUB_PROTOCOL_TEST_CASES
]


async def perform_test_from_obj(obj, pubsub_factory) -> None:
    """
    Perform pubsub tests from a test object, which is composed as follows:

    .. code-block:: python

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

    .. note::
        In adj_list, for any neighbors A and B, only list B as a neighbor of A
        or B as a neighbor of A once. Do NOT list both A: ["B"] and B:["A"] as the behavior
        is undefined (even if it may work)
    """  # noqa: E501
    # Step 1) Create graph
    adj_list = obj["adj_list"]
    node_list = obj["nodes"]
    node_map = {}
    pubsub_map = {}

    async with pubsub_factory(
        number=len(node_list), protocols=obj["supported_protocols"]
    ) as pubsubs:
        for node_id_str, pubsub in zip(node_list, pubsubs):
            node_map[node_id_str] = pubsub.host
            pubsub_map[node_id_str] = pubsub

        # Connect nodes and wait at least for 2 seconds
        async with trio.open_nursery() as nursery:
            for start_node_id in adj_list:
                # For each neighbor of start_node, create if does not yet exist,
                # then connect start_node to neighbor
                for neighbor_id in adj_list[start_node_id]:
                    nursery.start_soon(
                        connect, node_map[start_node_id], node_map[neighbor_id]
                    )
            nursery.start_soon(trio.sleep, 2)

        # Step 2) Subscribe to topics
        queues_map = {}
        topic_map = obj["topic_map"]

        async def subscribe_node(node_id, topic):
            if node_id not in queues_map:
                queues_map[node_id] = {}
            # Avoid repeated works
            if topic in queues_map[node_id]:
                # Checkpoint
                await trio.lowlevel.checkpoint()
                return
            sub = await pubsub_map[node_id].subscribe(topic)
            queues_map[node_id][topic] = sub

        async with trio.open_nursery() as nursery:
            for topic, node_ids in topic_map.items():
                for node_id in node_ids:
                    nursery.start_soon(subscribe_node, node_id, topic)
            nursery.start_soon(trio.sleep, 2)

        # Step 3) Publish messages
        topics_in_msgs_ordered = []
        messages = obj["messages"]

        for msg in messages:
            topics = msg["topics"]
            data = msg["data"]
            node_id = msg["node_id"]

            # Publish message - now uses single RPC package with several topics
            await pubsub_map[node_id].publish(topics, data)

            # For each topic in topics, add (topic, node_id, data) tuple to
            # ordered test list
            for topic in topics:
                topics_in_msgs_ordered.append((topic, node_id, data))
        # Allow time for publishing before continuing
        await trio.sleep(1)

        # Step 4) Check that all messages were received correctly.
        for topic, origin_node_id, data in topics_in_msgs_ordered:
            # Look at each node in each topic
            for node_id in topic_map[topic]:
                # Get message from subscription queue
                msg = await queues_map[node_id][topic].get()
                assert data == msg.data
                # Check the message origin
                assert node_map[origin_node_id].get_id().to_bytes() == msg.from_id

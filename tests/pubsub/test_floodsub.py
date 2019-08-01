import asyncio
import multiaddr
import pytest

from libp2p import new_node
from libp2p.peer.id import ID
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub

from tests.utils import cleanup, connect

from .configs import FLOODSUB_PROTOCOL_ID, LISTEN_MADDR
from .floodsub_integration_test_settings import (
    perform_test_from_obj,
    floodsub_protocol_pytest_params,
)


SUPPORTED_PROTOCOLS = [FLOODSUB_PROTOCOL_ID]
# pylint: disable=too-many-locals


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
    pubsub_a = Pubsub(node_a, floodsub_a, ID(b"\x12\x20" + b"a" * 32))
    floodsub_b = FloodSub(supported_protocols)
    pubsub_b = Pubsub(node_b, floodsub_b, ID(b"\x12\x20" + b"a" * 32))

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
        if i >= 2 ** (num_int_bytes * 8):
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


@pytest.mark.parametrize("test_case_obj", floodsub_protocol_pytest_params)
@pytest.mark.asyncio
async def test_gossipsub_run_with_floodsub_tests(test_case_obj):
    await perform_test_from_obj(test_case_obj, FloodSub)

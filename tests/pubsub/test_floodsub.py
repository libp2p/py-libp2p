import functools

import pytest
import trio

from libp2p.peer.id import ID
from libp2p.tools.factories import PubsubFactory
from libp2p.tools.pubsub.floodsub_integration_test_settings import (
    floodsub_protocol_pytest_params,
    perform_test_from_obj,
)
from libp2p.tools.utils import connect


@pytest.mark.trio
async def test_simple_two_nodes():
    async with PubsubFactory.create_batch_with_floodsub(2) as pubsubs_fsub:
        topic = "my_topic"
        data = b"some data"

        await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
        await trio.sleep(0.25)

        sub_b = await pubsubs_fsub[1].subscribe(topic)
        # Sleep to let a know of b's subscription
        await trio.sleep(0.25)

        await pubsubs_fsub[0].publish(topic, data)

        res_b = await sub_b.get()

        # Check that the msg received by node_b is the same
        # as the message sent by node_a
        assert ID(res_b.from_id) == pubsubs_fsub[0].host.get_id()
        assert res_b.data == data
        assert res_b.topicIDs == [topic]


@pytest.mark.trio
async def test_lru_cache_two_nodes(monkeypatch):
    # two nodes with cache_size of 4
    async with PubsubFactory.create_batch_with_floodsub(
        2, cache_size=4
    ) as pubsubs_fsub:
        # `node_a` send the following messages to node_b
        message_indices = [1, 1, 2, 1, 3, 1, 4, 1, 5, 1]
        # `node_b` should only receive the following
        expected_received_indices = [1, 2, 3, 4, 5, 1]

        topic = "my_topic"

        # Mock `get_msg_id` to make us easier to manipulate `msg_id` by `data`.
        def get_msg_id(msg):
            # Originally it is `(msg.seqno, msg.from_id)`
            return (msg.data, msg.from_id)

        import libp2p.pubsub.pubsub

        monkeypatch.setattr(libp2p.pubsub.pubsub, "get_msg_id", get_msg_id)

        await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
        await trio.sleep(0.25)

        sub_b = await pubsubs_fsub[1].subscribe(topic)
        await trio.sleep(0.25)

        def _make_testing_data(i: int) -> bytes:
            num_int_bytes = 4
            if i >= 2 ** (num_int_bytes * 8):
                raise ValueError("integer is too large to be serialized")
            return b"data" + i.to_bytes(num_int_bytes, "big")

        for index in message_indices:
            await pubsubs_fsub[0].publish(topic, _make_testing_data(index))
        await trio.sleep(0.25)

        for index in expected_received_indices:
            res_b = await sub_b.get()
            assert res_b.data == _make_testing_data(index)


@pytest.mark.parametrize("test_case_obj", floodsub_protocol_pytest_params)
@pytest.mark.trio
@pytest.mark.slow
async def test_gossipsub_run_with_floodsub_tests(test_case_obj, security_protocol):
    await perform_test_from_obj(
        test_case_obj,
        functools.partial(
            PubsubFactory.create_batch_with_floodsub,
            security_protocol=security_protocol,
        ),
    )

import functools

import pytest

from libp2p.peer.id import (
    ID,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    PubsubFactory,
)
from tests.utils.pubsub.floodsub_integration_test_settings import (
    floodsub_protocol_pytest_params,
    perform_test_from_obj,
)
from tests.utils.pubsub.wait import (
    wait_for,
    wait_for_pubsub_payload,
)


@pytest.mark.trio
async def test_simple_two_nodes():
    async with PubsubFactory.create_batch_with_floodsub(2) as pubsubs_fsub:
        topic = "my_topic"
        data = b"some data"

        await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
        await pubsubs_fsub[0].wait_for_peer(pubsubs_fsub[1].my_id)
        await pubsubs_fsub[1].wait_for_peer(pubsubs_fsub[0].my_id)

        sub_b = await pubsubs_fsub[1].subscribe(topic)
        await pubsubs_fsub[0].wait_for_subscription(pubsubs_fsub[1].my_id, topic)

        await pubsubs_fsub[0].publish(topic, data)

        res_b = await wait_for_pubsub_payload(sub_b, data)

        # Check that the msg received by node_b is the same
        # as the message sent by node_a
        assert ID(res_b.from_id) == pubsubs_fsub[0].host.get_id()
        assert res_b.data == data
        assert res_b.topicIDs == [topic]


@pytest.mark.trio
async def test_timed_cache_two_nodes():
    # Two nodes using LastSeenCache with a TTL of 10 seconds
    def get_msg_id(msg):
        return msg.data + msg.from_id

    async with PubsubFactory.create_batch_with_floodsub(
        2, seen_ttl=10, msg_id_constructor=get_msg_id
    ) as pubsubs_fsub:
        message_indices = [1, 1, 2, 1, 3, 1, 4, 1, 5, 1]
        expected_received_indices = [1, 2, 3, 4, 5]

        topic = "my_topic"

        await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
        await pubsubs_fsub[0].wait_for_peer(pubsubs_fsub[1].my_id)
        await pubsubs_fsub[1].wait_for_peer(pubsubs_fsub[0].my_id)

        sub_b = await pubsubs_fsub[1].subscribe(topic)
        await pubsubs_fsub[0].wait_for_subscription(pubsubs_fsub[1].my_id, topic)

        def _make_testing_data(i: int) -> bytes:
            num_int_bytes = 4
            if i >= 2 ** (num_int_bytes * 8):
                raise ValueError("integer is too large to be serialized")
            return b"data" + i.to_bytes(num_int_bytes, "big")

        for index in message_indices:
            await pubsubs_fsub[0].publish(topic, _make_testing_data(index))

        for index in expected_received_indices:
            res_b = await wait_for_pubsub_payload(sub_b, _make_testing_data(index))
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


@pytest.mark.trio
async def test_floodsub_peer_churn_subscription_resync():
    async with PubsubFactory.create_batch_with_floodsub(2) as (A, B):
        topic = "x"
        data = b"msg"

        sub_b = await B.subscribe(topic)

        # Connect
        await connect(A.host, B.host)
        await A.wait_for_peer(B.my_id)
        await B.wait_for_peer(A.my_id)
        await A.wait_for_subscription(B.my_id, topic)

        # Disconnect
        await B.host.disconnect(A.host.get_id())
        await wait_for(
            lambda: B.my_id not in A.peers and A.my_id not in B.peers,
            fail_msg="Peers still present after disconnect",
        )

        # Reconnect
        await connect(A.host, B.host)
        await A.wait_for_peer(B.my_id)
        await B.wait_for_peer(A.my_id)
        await A.wait_for_subscription(B.my_id, topic)

        # After reconnect, A must know B is subscribed
        await A.publish(topic, data)
        msg_b = await wait_for_pubsub_payload(sub_b, data)

        assert msg_b.data == data


@pytest.mark.trio
async def test_floodsub_dedup_loop_topology():
    async with PubsubFactory.create_batch_with_floodsub(3) as (A, B, C):
        topic = "z"
        data = b"dup"

        sub_a = await A.subscribe(topic)
        sub_b = await B.subscribe(topic)

        # form a loop: A-B-C-A
        await connect(A.host, B.host)
        await connect(B.host, C.host)
        await connect(C.host, A.host)

        await A.wait_for_peer(B.my_id)
        await B.wait_for_peer(A.my_id)
        await B.wait_for_peer(C.my_id)
        await C.wait_for_peer(B.my_id)
        await C.wait_for_peer(A.my_id)
        await A.wait_for_peer(C.my_id)

        await A.wait_for_subscription(B.my_id, topic)
        await B.wait_for_subscription(A.my_id, topic)
        await C.wait_for_subscription(A.my_id, topic)
        await C.wait_for_subscription(B.my_id, topic)

        # publish twice
        await C.publish(topic, data)
        await C.publish(topic, data)

        # A and B should get EXACTLY one message
        msg_a = await wait_for_pubsub_payload(sub_a, data)
        msg_b = await wait_for_pubsub_payload(sub_b, data)

        assert msg_a.data == data
        assert msg_b.data == data


@pytest.mark.trio
async def test_subscription_sync_on_late_joiner():
    async with PubsubFactory.create_batch_with_floodsub(3) as (A, B, C):
        topic = "sync"
        data = b"m"

        # B and C subscribe before connecting
        sub_c = await C.subscribe(topic)
        await B.subscribe(topic)

        # Connect them AFTER subscription
        await connect(A.host, B.host)
        await connect(A.host, C.host)

        await A.wait_for_peer(B.my_id)
        await B.wait_for_peer(A.my_id)
        await A.wait_for_peer(C.my_id)
        await C.wait_for_peer(A.my_id)

        await A.wait_for_subscription(B.my_id, topic)
        await A.wait_for_subscription(C.my_id, topic)

        await A.publish(topic, data)
        msg_c = await wait_for_pubsub_payload(sub_c, data)

        assert msg_c.data == data

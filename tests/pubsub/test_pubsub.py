import asyncio

import pytest

from libp2p.pubsub.pb import rpc_pb2

from tests.utils import (
    connect,
)


TESTING_TOPIC = "TEST_SUBSCRIBE"
TESTIND_DATA = b"data"


@pytest.mark.parametrize(
    "num_hosts",
    (1,),
)
@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe(pubsubs_fsub):
    await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in pubsubs_fsub[0].my_topics

    await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
    assert TESTING_TOPIC not in pubsubs_fsub[0].my_topics


@pytest.mark.parametrize(
    "num_hosts",
    (1,),
)
@pytest.mark.asyncio
async def test_re_subscribe(pubsubs_fsub):
    await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in pubsubs_fsub[0].my_topics

    await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in pubsubs_fsub[0].my_topics


@pytest.mark.parametrize(
    "num_hosts",
    (1,),
)
@pytest.mark.asyncio
async def test_re_unsubscribe(pubsubs_fsub):
    # Unsubscribe from topic we didn't even subscribe to
    assert "NOT_MY_TOPIC" not in pubsubs_fsub[0].my_topics
    await pubsubs_fsub[0].unsubscribe("NOT_MY_TOPIC")
    assert "NOT_MY_TOPIC" not in pubsubs_fsub[0].my_topics

    await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in pubsubs_fsub[0].my_topics

    await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
    assert TESTING_TOPIC not in pubsubs_fsub[0].my_topics

    await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
    assert TESTING_TOPIC not in pubsubs_fsub[0].my_topics


@pytest.mark.asyncio
async def test_peers_subscribe(pubsubs_fsub):
    await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
    await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
    # Yield to let 0 notify 1
    await asyncio.sleep(0.1)
    assert str(pubsubs_fsub[0].my_id) in pubsubs_fsub[1].peer_topics[TESTING_TOPIC]
    await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
    # Yield to let 0 notify 1
    await asyncio.sleep(0.1)
    assert str(pubsubs_fsub[0].my_id) not in pubsubs_fsub[1].peer_topics[TESTING_TOPIC]


@pytest.mark.parametrize(
    "num_hosts",
    (1,),
)
@pytest.mark.asyncio
async def test_get_hello_packet(pubsubs_fsub):
    def _get_hello_packet_topic_ids():
        packet = rpc_pb2.RPC()
        packet.ParseFromString(pubsubs_fsub[0].get_hello_packet())
        return tuple(
            sub.topicid
            for sub in packet.subscriptions
        )

    # pylint: disable=len-as-condition
    # Test: No subscription, so there should not be any topic ids in the hello packet.
    assert len(_get_hello_packet_topic_ids()) == 0

    # Test: After subscriptions, topic ids should be in the hello packet.
    topic_ids = ["t", "o", "p", "i", "c"]
    await asyncio.gather(*[
        pubsubs_fsub[0].subscribe(topic)
        for topic in topic_ids
    ])
    topic_ids_in_hello = _get_hello_packet_topic_ids()
    for topic in topic_ids:
        assert topic in topic_ids_in_hello


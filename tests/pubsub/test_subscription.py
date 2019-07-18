# pylint: disable=redefined-outer-name
import pytest

from libp2p import new_node
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.floodsub import FloodSub

SUPPORTED_PUBSUB_PROTOCOLS = ["/floodsub/1.0.0"]
TESTING_TOPIC = "TEST_SUBSCRIBE"


class NoConnNode:
    # pylint: disable=too-few-public-methods

    def __init__(self, host, pubsub):
        self.host = host
        self.pubsub = pubsub

    @classmethod
    async def create(cls):
        host = await new_node()
        floodsub = FloodSub(SUPPORTED_PUBSUB_PROTOCOLS)
        pubsub = Pubsub(host, floodsub, "test")
        return cls(host, pubsub)


@pytest.fixture
async def node():
    return await NoConnNode.create()


@pytest.mark.asyncio
async def test_subscribe_unsubscribe(node):
    await node.pubsub.subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in node.pubsub.my_topics

    await node.pubsub.unsubscribe(TESTING_TOPIC)
    assert TESTING_TOPIC not in node.pubsub.my_topics


@pytest.mark.asyncio
async def test_re_subscribe(node):
    await node.pubsub.subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in node.pubsub.my_topics

    await node.pubsub.subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in node.pubsub.my_topics


@pytest.mark.asyncio
async def test_re_unsubscribe(node):
    # Unsubscribe from topic we didn't even subscribe to
    assert "NOT_MY_TOPIC" not in node.pubsub.my_topics
    await node.pubsub.unsubscribe("NOT_MY_TOPIC")

    await node.pubsub.subscribe(TESTING_TOPIC)
    assert TESTING_TOPIC in node.pubsub.my_topics

    await node.pubsub.unsubscribe(TESTING_TOPIC)
    assert TESTING_TOPIC not in node.pubsub.my_topics

    await node.pubsub.unsubscribe(TESTING_TOPIC)
    assert TESTING_TOPIC not in node.pubsub.my_topics

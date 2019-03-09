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
from tests.pubsub.dummy_account_node import DummyAccountNode

# pylint: disable=too-many-locals

async def connect(node1, node2):
    # node1 connects to node2
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await node1.connect(info)

@pytest.mark.asyncio
async def test_simple_two_nodes():
    dummy1 = await DummyAccountNode.create()
    dummy2 = await DummyAccountNode.create()

    await connect(dummy1.libp2p_node, dummy2.libp2p_node)

    await asyncio.sleep(0.25)

    asyncio.ensure_future(dummy1.setup_crypto_networking())
    asyncio.ensure_future(dummy2.setup_crypto_networking())

    await asyncio.sleep(0.25)

    await dummy1.publish_set_crypto("aspyn", 10)

    await asyncio.sleep(0.25)

    # Check that all nodes have balances set properly (implying floodsub 
    # hit all nodes subscribed to the crypto topic)
    assert dummy1.get_balance("aspyn") == 10
    assert dummy2.get_balance("aspyn") == 10

    # Success, terminate pending tasks.
    await cleanup()

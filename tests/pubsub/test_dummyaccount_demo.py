import asyncio
import multiaddr
import pytest

from threading import Thread
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

def create_setup_in_new_thread_func(dummy_node):
    def setup_in_new_thread():
        asyncio.ensure_future(dummy_node.setup_crypto_networking())
    return setup_in_new_thread

@pytest.mark.asyncio
async def test_simple_two_nodes():
    dummy1 = await DummyAccountNode.create()
    dummy2 = await DummyAccountNode.create()

    await connect(dummy1.libp2p_node, dummy2.libp2p_node)

    await asyncio.sleep(0.25)

    thread1 = Thread(target=create_setup_in_new_thread_func(dummy1))
    thread1.run()
    thread2 = Thread(target=create_setup_in_new_thread_func(dummy2))
    thread2.run()
    # Thread.start_new_thread(setup_in_new_thread, (dummy1))
    # Thread.start_new_thread(setup_in_new_thread, (dummy2))
    # await dummy1.setup_crypto_networking()
    # await dummy2.setup_crypto_networking()

    await asyncio.sleep(0.25)

    await dummy1.publish_set_crypto("aspyn", 10)

    await asyncio.sleep(0.25)

    # Check that all nodes have balances set properly (implying floodsub 
    # hit all nodes subscribed to the crypto topic)
    assert dummy1.get_balance("aspyn") == 10
    assert dummy2.get_balance("aspyn") == 10

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_simple_three_nodes_line_topography():
    dummy1 = await DummyAccountNode.create()
    dummy2 = await DummyAccountNode.create()
    dummy3 = await DummyAccountNode.create()

    await connect(dummy1.libp2p_node, dummy2.libp2p_node)
    await connect(dummy2.libp2p_node, dummy3.libp2p_node)

    await asyncio.sleep(0.25)

    thread1 = Thread(target=create_setup_in_new_thread_func(dummy1))
    thread1.run()
    thread2 = Thread(target=create_setup_in_new_thread_func(dummy2))
    thread2.run()
    thread3 = Thread(target=create_setup_in_new_thread_func(dummy3))
    thread3.run()
    # Thread.start_new_thread(setup_in_new_thread, (dummy1))
    # Thread.start_new_thread(setup_in_new_thread, (dummy2))
    # await dummy1.setup_crypto_networking()
    # await dummy2.setup_crypto_networking()

    await asyncio.sleep(0.25)

    await dummy1.publish_set_crypto("aspyn", 10)

    await asyncio.sleep(0.25)

    # Check that all nodes have balances set properly (implying floodsub 
    # hit all nodes subscribed to the crypto topic)
    assert dummy1.get_balance("aspyn") == 10
    assert dummy2.get_balance("aspyn") == 10
    assert dummy3.get_balance("aspyn") == 10

    # Success, terminate pending tasks.
    await cleanup()

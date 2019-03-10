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

async def perform_test(num_nodes, adjacency_map, action_func, assertion_func):
    dummy_nodes = []
    for i in range(num_nodes):
        dummy_nodes.append(await DummyAccountNode.create())

    for source_num in adjacency_map:
        target_nums = adjacency_map[source_num]
        for target_num in target_nums:
            await connect(dummy_nodes[source_num].libp2p_node, \
                dummy_nodes[target_num].libp2p_node)

    await asyncio.sleep(0.25)

    for dummy_node in dummy_nodes:
        thread = Thread(target=create_setup_in_new_thread_func(dummy_node))
        thread.run()

    await asyncio.sleep(0.25)

    await action_func(dummy_nodes)

    await asyncio.sleep(0.25)

    for dummy_node in dummy_nodes:
        assertion_func(dummy_node)

    # Success, terminate pending tasks.
    await cleanup()

@pytest.mark.asyncio
async def test_simple_two_nodes():
    num_nodes = 2
    adj_map = {0: [1]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 10)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 10

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

@pytest.mark.asyncio
async def test_simple_three_nodes_line_topography():
    num_nodes = 3
    adj_map = {0: [1], 1: [2]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 10)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 10

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

@pytest.mark.asyncio
async def test_simple_three_nodes_triangle_topography():
    num_nodes = 3
    adj_map = {0: [1, 2], 1: [2]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 20

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

@pytest.mark.asyncio
async def test_simple_seven_nodes_tree_topography():
    num_nodes = 7
    adj_map = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 20

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

@pytest.mark.asyncio
async def test_set_then_send_from_root_seven_nodes_tree_topography():
    num_nodes = 7
    adj_map = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)
        await asyncio.sleep(0.25)
        await dummy_nodes[0].publish_send_crypto("aspyn", "alex", 5)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 15
        assert dummy_node.get_balance("alex") == 5

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

@pytest.mark.asyncio
async def test_set_then_send_from_different_leafs_seven_nodes_tree_topography():
    num_nodes = 7
    adj_map = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    async def action_func(dummy_nodes):
        await dummy_nodes[6].publish_set_crypto("aspyn", 20)
        await asyncio.sleep(0.25)
        await dummy_nodes[4].publish_send_crypto("aspyn", "alex", 5)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 15
        assert dummy_node.get_balance("alex") == 5

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

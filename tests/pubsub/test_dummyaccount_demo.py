import asyncio
from threading import Thread

import pytest

from libp2p.tools.utils import connect

from .dummy_account_node import DummyAccountNode


def create_setup_in_new_thread_func(dummy_node):
    def setup_in_new_thread():
        asyncio.ensure_future(dummy_node.setup_crypto_networking())

    return setup_in_new_thread


async def perform_test(num_nodes, adjacency_map, action_func, assertion_func):
    """
    Helper function to allow for easy construction of custom tests for dummy
    account nodes in various network topologies.

    :param num_nodes: number of nodes in the test
    :param adjacency_map: adjacency map defining each node and its list of neighbors
    :param action_func: function to execute that includes actions by the nodes,
    such as send crypto and set crypto
    :param assertion_func: assertions for testing the results of the actions are correct
    """

    # Create nodes
    dummy_nodes = []
    for _ in range(num_nodes):
        dummy_nodes.append(await DummyAccountNode.create())

    # Create network
    for source_num in adjacency_map:
        target_nums = adjacency_map[source_num]
        for target_num in target_nums:
            await connect(
                dummy_nodes[source_num].libp2p_node, dummy_nodes[target_num].libp2p_node
            )

    # Allow time for network creation to take place
    await asyncio.sleep(0.25)

    # Start a thread for each node so that each node can listen and respond
    # to messages on its own thread, which will avoid waiting indefinitely
    # on the main thread. On this thread, call the setup func for the node,
    # which subscribes the node to the CRYPTO_TOPIC topic
    for dummy_node in dummy_nodes:
        thread = Thread(target=create_setup_in_new_thread_func(dummy_node))
        thread.run()

    # Allow time for nodes to subscribe to CRYPTO_TOPIC topic
    await asyncio.sleep(0.25)

    # Perform action function
    await action_func(dummy_nodes)

    # Allow time for action function to be performed (i.e. messages to propogate)
    await asyncio.sleep(1)

    # Perform assertion function
    for dummy_node in dummy_nodes:
        assertion_func(dummy_node)

    # Success, terminate pending tasks.


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


@pytest.mark.asyncio
async def test_simple_five_nodes_ring_topography():
    num_nodes = 5
    adj_map = {0: [1], 1: [2], 2: [3], 3: [4], 4: [0]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 20

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.asyncio
async def test_set_then_send_from_diff_nodes_five_nodes_ring_topography():
    num_nodes = 5
    adj_map = {0: [1], 1: [2], 2: [3], 3: [4], 4: [0]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("alex", 20)
        await asyncio.sleep(0.25)
        await dummy_nodes[3].publish_send_crypto("alex", "rob", 12)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("alex") == 8
        assert dummy_node.get_balance("rob") == 12

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_set_then_send_from_five_diff_nodes_five_nodes_ring_topography():
    num_nodes = 5
    adj_map = {0: [1], 1: [2], 2: [3], 3: [4], 4: [0]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("alex", 20)
        await asyncio.sleep(1)
        await dummy_nodes[1].publish_send_crypto("alex", "rob", 3)
        await asyncio.sleep(1)
        await dummy_nodes[2].publish_send_crypto("rob", "aspyn", 2)
        await asyncio.sleep(1)
        await dummy_nodes[3].publish_send_crypto("aspyn", "zx", 1)
        await asyncio.sleep(1)
        await dummy_nodes[4].publish_send_crypto("zx", "raul", 1)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("alex") == 17
        assert dummy_node.get_balance("rob") == 1
        assert dummy_node.get_balance("aspyn") == 1
        assert dummy_node.get_balance("zx") == 0
        assert dummy_node.get_balance("raul") == 1

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

import pytest
import trio

from libp2p.tools.utils import (
    connect,
)
from tests.utils.pubsub.dummy_account_node import (
    DummyAccountNode,
)


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
    async with DummyAccountNode.create(num_nodes) as dummy_nodes:
        # Create connections between nodes according to `adjacency_map`
        async with trio.open_nursery() as nursery:
            for source_num in adjacency_map:
                target_nums = adjacency_map[source_num]
                for target_num in target_nums:
                    nursery.start_soon(
                        connect,
                        dummy_nodes[source_num].host,
                        dummy_nodes[target_num].host,
                    )

        # Allow time for network creation to take place
        await trio.sleep(0.25)

        # Perform action function
        await action_func(dummy_nodes)

        # Allow time for action function to be performed (i.e. messages to propogate)
        await trio.sleep(1)

        # Perform assertion function
        for dummy_node in dummy_nodes:
            assertion_func(dummy_node)

    # Success, terminate pending tasks.


@pytest.mark.trio
async def test_simple_two_nodes():
    num_nodes = 2
    adj_map = {0: [1]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 10)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 10

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_simple_three_nodes_line_topography():
    num_nodes = 3
    adj_map = {0: [1], 1: [2]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 10)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 10

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_simple_three_nodes_triangle_topography():
    num_nodes = 3
    adj_map = {0: [1, 2], 1: [2]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 20

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_simple_seven_nodes_tree_topography():
    num_nodes = 7
    adj_map = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 20

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_set_then_send_from_root_seven_nodes_tree_topography():
    num_nodes = 7
    adj_map = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)
        await trio.sleep(0.25)
        await dummy_nodes[0].publish_send_crypto("aspyn", "alex", 5)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 15
        assert dummy_node.get_balance("alex") == 5

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_set_then_send_from_different_leafs_seven_nodes_tree_topography():
    num_nodes = 7
    adj_map = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    async def action_func(dummy_nodes):
        await dummy_nodes[6].publish_set_crypto("aspyn", 20)
        await trio.sleep(0.25)
        await dummy_nodes[4].publish_send_crypto("aspyn", "alex", 5)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 15
        assert dummy_node.get_balance("alex") == 5

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_simple_five_nodes_ring_topography():
    num_nodes = 5
    adj_map = {0: [1], 1: [2], 2: [3], 3: [4], 4: [0]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("aspyn", 20)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("aspyn") == 20

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
async def test_set_then_send_from_diff_nodes_five_nodes_ring_topography():
    num_nodes = 5
    adj_map = {0: [1], 1: [2], 2: [3], 3: [4], 4: [0]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("alex", 20)
        await trio.sleep(0.25)
        await dummy_nodes[3].publish_send_crypto("alex", "rob", 12)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("alex") == 8
        assert dummy_node.get_balance("rob") == 12

    await perform_test(num_nodes, adj_map, action_func, assertion_func)


@pytest.mark.trio
@pytest.mark.slow
async def test_set_then_send_from_five_diff_nodes_five_nodes_ring_topography():
    num_nodes = 5
    adj_map = {0: [1], 1: [2], 2: [3], 3: [4], 4: [0]}

    async def action_func(dummy_nodes):
        await dummy_nodes[0].publish_set_crypto("alex", 20)
        await trio.sleep(1)
        await dummy_nodes[1].publish_send_crypto("alex", "rob", 3)
        await trio.sleep(1)
        await dummy_nodes[2].publish_send_crypto("rob", "aspyn", 2)
        await trio.sleep(1)
        await dummy_nodes[3].publish_send_crypto("aspyn", "zx", 1)
        await trio.sleep(1)
        await dummy_nodes[4].publish_send_crypto("zx", "raul", 1)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("alex") == 17
        assert dummy_node.get_balance("rob") == 1
        assert dummy_node.get_balance("aspyn") == 1
        assert dummy_node.get_balance("zx") == 0
        assert dummy_node.get_balance("raul") == 1

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

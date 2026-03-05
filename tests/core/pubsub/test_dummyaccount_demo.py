from collections.abc import (
    Callable,
)

import pytest
import trio

from libp2p.tools.utils import (
    connect,
)
from tests.utils.pubsub.dummy_account_node import (
    DummyAccountNode,
)


async def wait_for_convergence(
    nodes: tuple[DummyAccountNode, ...],
    check: Callable[[DummyAccountNode], bool],
    timeout: float = 10.0,
    poll_interval: float = 0.02,
    log_success: bool = False,
    raise_last_exception_on_timeout: bool = True,
) -> None:
    """
    Wait until all nodes satisfy the check condition.

    Returns as soon as convergence is reached, otherwise raises TimeoutError.
    Convergence already guarantees all nodes satisfy the check, so callers need
    not run a second assertion pass after this returns.
    """
    start_time = trio.current_time()

    last_exception: Exception | None = None
    last_exception_node: int | None = None

    while True:
        failed_indices: list[int] = []
        for i, node in enumerate(nodes):
            try:
                ok = check(node)
            except Exception as exc:
                ok = False
                last_exception = exc
                last_exception_node = i
            if not ok:
                failed_indices.append(i)

        if not failed_indices:
            elapsed = trio.current_time() - start_time
            if log_success:
                print(f"✓ Converged in {elapsed:.3f}s with {len(nodes)} nodes")
            return

        elapsed = trio.current_time() - start_time
        if elapsed > timeout:
            if raise_last_exception_on_timeout and last_exception is not None:
                # Preserve the underlying assertion/exception signal (and its message)
                # instead of hiding it behind a generic timeout.
                node_hint = (
                    f" (node index {last_exception_node})"
                    if last_exception_node is not None
                    else ""
                )
                raise AssertionError(
                    f"Convergence failed{node_hint}: {last_exception}"
                ) from last_exception

            raise TimeoutError(
                f"Convergence timeout after {elapsed:.2f}s. "
                f"Failed nodes: {failed_indices}. "
                f"(Hint: run with -s and pass log_success=True for timing logs)"
            )

        await trio.sleep(poll_interval)


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

        # Wait until all nodes satisfy the expected final state.
        def _check_final(node: DummyAccountNode) -> bool:
            assertion_func(node)
            return True

        await wait_for_convergence(dummy_nodes, _check_final, timeout=10.0)

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
        await wait_for_convergence(
            dummy_nodes, lambda n: n.get_balance("aspyn") == 20, timeout=10.0
        )
        await dummy_nodes[0].publish_send_crypto("aspyn", "alex", 5)
        # Wait for the send operation to propagate to all nodes
        await wait_for_convergence(
            dummy_nodes,
            lambda n: n.get_balance("aspyn") == 15 and n.get_balance("alex") == 5,
            timeout=10.0,
        )

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
        await wait_for_convergence(
            dummy_nodes, lambda n: n.get_balance("aspyn") == 20, timeout=10.0
        )
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
        # Ensure `set` has reached all nodes before sending, otherwise late `set`
        # can overwrite the effects of `send` on nodes
        # that receive messages out-of-order.
        await wait_for_convergence(
            dummy_nodes, lambda n: n.get_balance("alex") == 20, timeout=10.0
        )
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
        await wait_for_convergence(
            dummy_nodes, lambda n: n.get_balance("alex") == 20, timeout=10.0
        )
        await dummy_nodes[1].publish_send_crypto("alex", "rob", 3)
        await wait_for_convergence(
            dummy_nodes,
            lambda n: n.get_balance("alex") == 17 and n.get_balance("rob") == 3,
            timeout=10.0,
        )
        await dummy_nodes[2].publish_send_crypto("rob", "aspyn", 2)
        await wait_for_convergence(
            dummy_nodes,
            lambda n: n.get_balance("alex") == 17
            and n.get_balance("rob") == 1
            and n.get_balance("aspyn") == 2,
            timeout=10.0,
        )
        await dummy_nodes[3].publish_send_crypto("aspyn", "zx", 1)
        await wait_for_convergence(
            dummy_nodes,
            lambda n: n.get_balance("alex") == 17
            and n.get_balance("rob") == 1
            and n.get_balance("aspyn") == 1
            and n.get_balance("zx") == 1,
            timeout=10.0,
        )
        await dummy_nodes[4].publish_send_crypto("zx", "raul", 1)

    def assertion_func(dummy_node):
        assert dummy_node.get_balance("alex") == 17
        assert dummy_node.get_balance("rob") == 1
        assert dummy_node.get_balance("aspyn") == 1
        assert dummy_node.get_balance("zx") == 0
        assert dummy_node.get_balance("raul") == 1

    await perform_test(num_nodes, adj_map, action_func, assertion_func)

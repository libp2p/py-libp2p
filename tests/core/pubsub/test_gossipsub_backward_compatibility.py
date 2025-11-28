import functools

import pytest
import trio

from libp2p.tools.constants import (
    FLOODSUB_PROTOCOL_ID,
)
from tests.utils.factories import (
    PubsubFactory,
)
from tests.utils.pubsub.floodsub_integration_test_settings import (
    floodsub_protocol_pytest_params,
    perform_test_from_obj,
)


@pytest.mark.parametrize("test_case_obj", floodsub_protocol_pytest_params)
@pytest.mark.trio
@pytest.mark.slow
async def test_gossipsub_run_with_floodsub_tests(test_case_obj):
    """
    Test GossipSub compatibility with FloodSub protocol using integration test cases.
    
    This test ensures proper resource cleanup to prevent pytest worker crashes
    in CI environments, particularly for complex topologies like seven_nodes_tree.
    """
    # Add timeout to prevent hanging tests from causing worker crashes
    # Use generous timeout for complex topologies (seven nodes tree, etc.)
    timeout_seconds = 180  # 3 minutes for complex test cases
    
    with trio.fail_after(timeout_seconds):
        try:
            await perform_test_from_obj(
                test_case_obj,
                functools.partial(
                    PubsubFactory.create_batch_with_gossipsub,
                    protocols=[FLOODSUB_PROTOCOL_ID],
                    degree=3,
                    degree_low=2,
                    degree_high=4,
                    time_to_live=30,
                ),
            )
        except trio.TooSlowError:
            # Handle timeout gracefully to prevent worker crash
            pytest.fail(
                f"Test case '{test_case_obj.get('test_name', 'unknown')}' "
                f"timed out after {timeout_seconds} seconds"
            )
        except Exception as e:
            # Log the error for debugging but don't let it crash the worker
            test_name = test_case_obj.get("test_name", "unknown")
            pytest.fail(f"Test case '{test_name}' failed with error: {e}")
        finally:
            # Ensure proper cleanup by yielding control and allowing
            # any pending async operations to complete
            await trio.lowlevel.checkpoint()
            # Small delay to allow background cleanup to complete
            await trio.sleep(0.2)

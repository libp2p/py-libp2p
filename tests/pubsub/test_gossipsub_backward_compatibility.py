import functools

import pytest

from libp2p import new_node
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub

from tests.utils import cleanup

from .configs import (
    FLOODSUB_PROTOCOL_ID,
    LISTEN_MADDR,
)
from .floodsub_integration_test_settings import (
    perform_test_from_obj,
    floodsub_protocol_pytest_params,
)


# pylint: disable=too-many-locals
@pytest.mark.asyncio
async def test_gossipsub_initialize_with_floodsub_protocol():
    node = await new_node(transport_opt=[str(LISTEN_MADDR)])

    await node.get_network().listen(LISTEN_MADDR)

    gossipsub = GossipSub([FLOODSUB_PROTOCOL_ID], 3, 2, 4, 30)
    pubsub = Pubsub(node, gossipsub, "a")

    # Did it work?
    assert gossipsub and pubsub

    await cleanup()


@pytest.mark.parametrize(
    "test_case_obj",
    floodsub_protocol_pytest_params,
)
@pytest.mark.asyncio
async def test_gossipsub_run_with_floodsub_tests(test_case_obj):
    await perform_test_from_obj(
        test_case_obj,
        functools.partial(
            GossipSub,
            degree=3,
            degree_low=2,
            degree_high=4,
            time_to_live=30,
        )
    )

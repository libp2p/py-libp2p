import functools

import pytest

from .configs import FLOODSUB_PROTOCOL_ID
from .factories import GossipsubFactory
from .floodsub_integration_test_settings import (
    perform_test_from_obj,
    floodsub_protocol_pytest_params,
)


@pytest.mark.asyncio
async def test_gossipsub_initialize_with_floodsub_protocol():
    GossipsubFactory(protocols=[FLOODSUB_PROTOCOL_ID])


@pytest.mark.parametrize("test_case_obj", floodsub_protocol_pytest_params)
@pytest.mark.asyncio
async def test_gossipsub_run_with_floodsub_tests(test_case_obj):
    await perform_test_from_obj(
        test_case_obj,
        functools.partial(
            GossipsubFactory, degree=3, degree_low=2, degree_high=4, time_to_live=30
        ),
    )

import functools

import pytest

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

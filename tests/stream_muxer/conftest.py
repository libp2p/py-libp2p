import asyncio

import pytest

from tests.factories import mplex_conn_pair_factory


@pytest.fixture
async def mplex_conn_pair(is_host_secure):
    mplex_conn_0, swarm_0, mplex_conn_1, swarm_1 = await mplex_conn_pair_factory(
        is_host_secure
    )
    try:
        yield mplex_conn_0, mplex_conn_1
    finally:
        await asyncio.gather(*[swarm_0.close(), swarm_1.close()])

import pytest

from tests.utils.factories import (
    net_stream_pair_factory,
    swarm_conn_pair_factory,
    swarm_pair_factory,
)


@pytest.fixture
async def net_stream_pair(security_protocol):
    async with net_stream_pair_factory(
        security_protocol=security_protocol
    ) as net_stream_pair:
        yield net_stream_pair


@pytest.fixture
async def swarm_pair(security_protocol):
    async with swarm_pair_factory(security_protocol=security_protocol) as swarms:
        yield swarms


@pytest.fixture
async def swarm_conn_pair(security_protocol):
    async with swarm_conn_pair_factory(
        security_protocol=security_protocol
    ) as swarm_conn_pair:
        yield swarm_conn_pair

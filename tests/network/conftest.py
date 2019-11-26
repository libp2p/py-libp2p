import asyncio

import pytest

from libp2p.tools.factories import (
    net_stream_pair_factory,
    swarm_conn_pair_factory,
    swarm_pair_factory,
)


@pytest.fixture
async def net_stream_pair(is_host_secure):
    async with net_stream_pair_factory(is_host_secure) as net_stream_pair:
        yield net_stream_pair


@pytest.fixture
async def swarm_pair(is_host_secure):
    async with swarm_pair_factory(is_host_secure) as swarms:
        yield swarms


@pytest.fixture
async def swarm_conn_pair(is_host_secure):
    async with swarm_conn_pair_factory(is_host_secure) as swarm_conn_pair:
        yield swarm_conn_pair

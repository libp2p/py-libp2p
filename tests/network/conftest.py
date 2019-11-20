import asyncio

import pytest

from libp2p.tools.factories import (
    net_stream_pair_factory,
    swarm_conn_pair_factory,
    swarm_pair_factory,
)


@pytest.fixture
async def net_stream_pair(is_host_secure):
    stream_0, host_0, stream_1, host_1 = await net_stream_pair_factory(is_host_secure)
    try:
        yield stream_0, stream_1
    finally:
        await asyncio.gather(*[host_0.close(), host_1.close()])


@pytest.fixture
async def swarm_pair(is_host_secure):
    swarm_0, swarm_1 = await swarm_pair_factory(is_host_secure)
    try:
        yield swarm_0, swarm_1
    finally:
        await asyncio.gather(*[swarm_0.close(), swarm_1.close()])


@pytest.fixture
async def swarm_conn_pair(is_host_secure):
    conn_0, swarm_0, conn_1, swarm_1 = await swarm_conn_pair_factory(is_host_secure)
    try:
        yield conn_0, conn_1
    finally:
        await asyncio.gather(*[swarm_0.close(), swarm_1.close()])

import asyncio

import pytest

from libp2p.tools.factories import mplex_conn_pair_factory, mplex_stream_pair_factory


@pytest.fixture
async def mplex_conn_pair(is_host_secure):
    async with mplex_conn_pair_factory(is_host_secure) as mplex_conn_pair:
        assert mplex_conn_pair[0].is_initiator
        assert not mplex_conn_pair[1].is_initiator
        yield mplex_conn_pair[0], mplex_conn_pair[1]


@pytest.fixture
async def mplex_stream_pair(is_host_secure):
    async with mplex_stream_pair_factory(is_host_secure) as mplex_stream_pair:
        yield mplex_stream_pair

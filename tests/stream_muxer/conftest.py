import pytest

from libp2p.tools.factories import mplex_conn_pair_factory, mplex_stream_pair_factory


@pytest.fixture
async def mplex_conn_pair(security_protocol):
    async with mplex_conn_pair_factory(
        security_protocol=security_protocol
    ) as mplex_conn_pair:
        assert mplex_conn_pair[0].is_initiator
        assert not mplex_conn_pair[1].is_initiator
        yield mplex_conn_pair[0], mplex_conn_pair[1]


@pytest.fixture
async def mplex_stream_pair(security_protocol):
    async with mplex_stream_pair_factory(
        security_protocol=security_protocol
    ) as mplex_stream_pair:
        yield mplex_stream_pair

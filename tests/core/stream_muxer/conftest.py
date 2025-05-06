import pytest

from tests.utils.factories import (
    mplex_conn_pair_factory,
    mplex_stream_pair_factory,
    yamux_conn_pair_factory,
    yamux_stream_pair_factory,
)


@pytest.fixture
async def yamux_conn_pair(security_protocol):
    async with yamux_conn_pair_factory(
        security_protocol=security_protocol
    ) as yamux_conn_pair:
        assert yamux_conn_pair[0].is_initiator
        assert not yamux_conn_pair[1].is_initiator
        yield yamux_conn_pair[0], yamux_conn_pair[1]


@pytest.fixture
async def yamux_stream_pair(security_protocol):
    async with yamux_stream_pair_factory(
        security_protocol=security_protocol
    ) as yamux_stream_pair:
        yield yamux_stream_pair


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

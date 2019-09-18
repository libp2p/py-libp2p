import pytest


@pytest.mark.asyncio
async def test_mplex_conn(mplex_conn_pair):
    conn_0, conn_1 = mplex_conn_pair

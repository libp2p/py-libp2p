import pytest

from libp2p.tools.factories import noise_conn_factory


@pytest.mark.trio
async def test_noise_transport(nursery):
    async with noise_conn_factory(nursery):
        pass


@pytest.mark.trio
async def test_noise_connection():
    async with noise_conn_factory() as conns:
        local_conn, remote_conn = conns

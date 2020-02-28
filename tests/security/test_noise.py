import pytest

from libp2p.tools.factories import noise_conn_factory

DATA = b"testing_123"


@pytest.mark.trio
async def test_noise_transport(nursery):
    async with noise_conn_factory(nursery):
        pass


@pytest.mark.trio
async def test_noise_connection(nursery):
    async with noise_conn_factory(nursery) as conns:
        local_conn, remote_conn = conns
        await local_conn.write(DATA)
        read_data = await remote_conn.read(len(DATA))
        assert read_data == DATA

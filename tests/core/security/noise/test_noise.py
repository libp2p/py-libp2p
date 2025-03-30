import pytest

from libp2p.security.noise.messages import (
    NoiseHandshakePayload,
)
from tests.utils.factories import (
    noise_conn_factory,
    noise_handshake_payload_factory,
)

DATA_0 = b"data_0"
DATA_1 = b"1" * 1000
DATA_2 = b"data_2"


@pytest.mark.trio
async def test_noise_transport(nursery):
    async with noise_conn_factory(nursery):
        pass


@pytest.mark.trio
async def test_noise_connection(nursery):
    async with noise_conn_factory(nursery) as conns:
        local_conn, remote_conn = conns
        await local_conn.write(DATA_0)
        await local_conn.write(DATA_1)
        assert DATA_0 == (await remote_conn.read(len(DATA_0)))
        assert DATA_1 == (await remote_conn.read(len(DATA_1)))
        await local_conn.write(DATA_2)
        assert DATA_2 == (await remote_conn.read(len(DATA_2)))


def test_noise_handshake_payload():
    payload = noise_handshake_payload_factory()
    payload_serialized = payload.serialize()
    payload_deserialized = NoiseHandshakePayload.deserialize(payload_serialized)
    assert payload == payload_deserialized

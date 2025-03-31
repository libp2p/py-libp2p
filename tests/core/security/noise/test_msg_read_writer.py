import pytest

from libp2p.security.noise.io import (
    MAX_NOISE_MESSAGE_LEN,
    NoisePacketReadWriter,
)
from tests.utils.factories import (
    raw_conn_factory,
)


@pytest.mark.parametrize(
    "noise_msg",
    (b"", b"data", pytest.param(b"A" * MAX_NOISE_MESSAGE_LEN, id="maximum length")),
)
@pytest.mark.trio
async def test_noise_msg_read_write_round_trip(nursery, noise_msg):
    async with raw_conn_factory(nursery) as conns:
        reader, writer = (
            NoisePacketReadWriter(conns[0]),
            NoisePacketReadWriter(conns[1]),
        )
        await writer.write_msg(noise_msg)
        assert (await reader.read_msg()) == noise_msg


@pytest.mark.trio
async def test_noise_msg_write_too_long(nursery):
    async with raw_conn_factory(nursery) as conns:
        writer = NoisePacketReadWriter(conns[0])
        with pytest.raises(ValueError):
            await writer.write_msg(b"1" * (MAX_NOISE_MESSAGE_LEN + 1))

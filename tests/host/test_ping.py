import asyncio
import secrets

import pytest

from libp2p.host.ping import ID, PING_LENGTH
from libp2p.tools.factories import pair_of_connected_hosts


@pytest.mark.asyncio
async def test_ping_once():
    async with pair_of_connected_hosts() as (host_a, host_b):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        some_ping = secrets.token_bytes(PING_LENGTH)
        await stream.write(some_ping)
        some_pong = await stream.read(PING_LENGTH)
        assert some_ping == some_pong
        await stream.close()


SOME_PING_COUNT = 3


@pytest.mark.asyncio
async def test_ping_several():
    async with pair_of_connected_hosts() as (host_a, host_b):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        for _ in range(SOME_PING_COUNT):
            some_ping = secrets.token_bytes(PING_LENGTH)
            await stream.write(some_ping)
            some_pong = await stream.read(PING_LENGTH)
            assert some_ping == some_pong
            # NOTE: simulate some time to sleep to mirror a real
            # world usage where a peer sends pings on some periodic interval
            # NOTE: this interval can be `0` for this test.
            await asyncio.sleep(0)  # todo: remove sleep or justify existence
        await stream.close()

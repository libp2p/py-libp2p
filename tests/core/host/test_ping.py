import secrets

import pytest
import trio

from libp2p.host.ping import (
    ID,
    PING_LENGTH,
    PingService,
)
from tests.utils.factories import (
    host_pair_factory,
)


@pytest.mark.trio
async def test_ping_once(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        some_ping = secrets.token_bytes(PING_LENGTH)
        await stream.write(some_ping)
        await trio.sleep(0.01)
        some_pong = await stream.read(PING_LENGTH)
        assert some_ping == some_pong
        await stream.close()


SOME_PING_COUNT = 3


@pytest.mark.trio
async def test_ping_several(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        for _ in range(SOME_PING_COUNT):
            some_ping = secrets.token_bytes(PING_LENGTH)
            await stream.write(some_ping)
            some_pong = await stream.read(PING_LENGTH)
            assert some_ping == some_pong
            # NOTE: simulate some time to sleep to mirror a real
            # world usage where a peer sends pings on some periodic interval
            # NOTE: this interval can be `0` for this test.
            await trio.sleep(0)
        await stream.close()


@pytest.mark.trio
async def test_ping_service_once(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        ping_service = PingService(host_b)
        rtts = await ping_service.ping(host_a.get_id())
        assert len(rtts) == 1
        assert rtts[0] < 10**6


@pytest.mark.trio
async def test_ping_service_several(security_protocol):
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        ping_service = PingService(host_b)
        rtts = await ping_service.ping(host_a.get_id(), ping_amt=SOME_PING_COUNT)
        assert len(rtts) == SOME_PING_COUNT
        for rtt in rtts:
            assert rtt < 10**6

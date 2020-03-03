import secrets

import pytest
import trio

from libp2p.host.ping import ID, PING_LENGTH, PingService
from libp2p.tools.factories import host_pair_factory


@pytest.mark.trio
async def test_ping_once(is_host_secure):
    async with host_pair_factory(is_host_secure) as (host_a, host_b):
        stream = await host_b.new_stream(host_a.get_id(), (ID,))
        some_ping = secrets.token_bytes(PING_LENGTH)
        await stream.write(some_ping)
        await trio.sleep(0.01)
        some_pong = await stream.read(PING_LENGTH)
        assert some_ping == some_pong
        await stream.close()


SOME_PING_COUNT = 3


@pytest.mark.trio
async def test_ping_several(is_host_secure):
    async with host_pair_factory(is_host_secure) as (host_a, host_b):
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
async def test_ping_service_once(is_host_secure):
    async with host_pair_factory(is_host_secure) as (host_a, host_b):
        ping_service = PingService(host_b)
        rtts = await ping_service.ping(host_a.get_id())
        assert len(rtts) == 1
        assert rtts[0] < 10 ** 6  # rtt is in miliseconds


@pytest.mark.trio
async def test_ping_service_several(is_host_secure):
    async with host_pair_factory(is_host_secure) as (host_a, host_b):
        ping_service = PingService(host_b)
        rtts = await ping_service.ping(host_a.get_id(), ping_amount=SOME_PING_COUNT)
        assert len(rtts) == SOME_PING_COUNT
        for rtt in rtts:
            assert rtt < 10 ** 6  # rtt is in miliseconds


@pytest.mark.trio
async def test_ping_service_loop(is_host_secure):
    async with host_pair_factory(is_host_secure) as (host_a, host_b):
        ping_service = PingService(host_b)
        ping_loop = await ping_service.ping_loop(
            host_a.get_id(), ping_limit=SOME_PING_COUNT
        )
        async for rtt in ping_loop:
            assert rtt < 10 ** 6


@pytest.mark.trio
async def test_ping_service_loop_infinite(is_host_secure):
    async with host_pair_factory(is_host_secure) as (host_a, host_b):
        ping_service = PingService(host_b)
        ping_loop = await ping_service.ping_loop(host_a.get_id())
        with trio.move_on_after(1):  # breaking loop after one second
            async for rtt in ping_loop:
                assert rtt < 10 ** 6

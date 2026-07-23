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
        assert 0 <= rtts[0] < 1000


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
            assert 0 <= rtt < 1000


@pytest.mark.trio
async def test_ping_mismatch_raises_value_error(security_protocol):
    """Bare `raise` was replaced with ValueError — verify it propagates cleanly."""
    from unittest.mock import AsyncMock
    from libp2p.host.ping import PING_LENGTH, _ping

    fake_stream = AsyncMock()
    fake_stream.write = AsyncMock(return_value=None)
    # Return wrong bytes so mismatch is triggered
    fake_stream.read = AsyncMock(return_value=b"\x00" * PING_LENGTH)

    with pytest.raises(ValueError, match="Ping payload mismatch"):
        await _ping(fake_stream)


@pytest.mark.trio
async def test_ping_service_validates_ping_amt():
    """ping_amt < 1 must raise immediately, not hang."""
    from libp2p.host.ping import PingService
    from unittest.mock import MagicMock

    svc = PingService(MagicMock())
    with pytest.raises(ValueError, match="ping_amt must be >= 1"):
        await svc.ping(MagicMock(), ping_amt=0)

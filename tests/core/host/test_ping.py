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
    from unittest.mock import MagicMock

    from libp2p.host.ping import PingService

    svc = PingService(MagicMock())
    with pytest.raises(ValueError, match="ping_amt must be >= 1"):
        await svc.ping(MagicMock(), ping_amt=0)


@pytest.mark.trio
async def test_ping_survives_short_reads():
    """
    Both MplexStream.read() and Yamux's read_stream() explicitly document
    and implement short-read semantics: read(n) may legitimately return
    fewer than n bytes if the full amount isn't buffered yet, unlike
    go-libp2p's io.ReadFull-based handler which always blocks for the
    full PingSize. A correct/valid 32-byte pong delivered across more than
    one read() call must not be reported as a payload mismatch.
    """
    from unittest.mock import AsyncMock

    from libp2p.host.ping import PING_LENGTH, _ping

    pong = secrets.token_bytes(PING_LENGTH)
    fake_stream = AsyncMock()
    fake_stream.write = AsyncMock(return_value=None)
    # Simulate the pong arriving in three separate short chunks, as a real
    # muxed stream is permitted to deliver it.
    fake_stream.read = AsyncMock(side_effect=[pong[:7], pong[7:19], pong[19:]])

    import libp2p.host.ping as ping_mod

    original_token_bytes = ping_mod.secrets.token_bytes
    ping_mod.secrets.token_bytes = lambda n: pong
    try:
        rtt = await _ping(fake_stream)
    finally:
        ping_mod.secrets.token_bytes = original_token_bytes

    assert rtt >= 0
    assert fake_stream.read.await_count == 3


@pytest.mark.trio
async def test_handle_ping_survives_short_reads():
    """Responder side must reassemble a short-read ping before echoing it."""
    from unittest.mock import AsyncMock

    from libp2p.host.ping import PING_LENGTH, _handle_ping
    from libp2p.peer.id import ID as PeerID

    ping_payload = secrets.token_bytes(PING_LENGTH)
    fake_stream = AsyncMock()
    fake_stream.read = AsyncMock(
        side_effect=[ping_payload[:5], ping_payload[5:]]
    )
    fake_stream.write = AsyncMock(return_value=None)

    should_continue = await _handle_ping(fake_stream, PeerID(b"\x00" * 32))

    assert should_continue is True
    # Must echo back the full, correctly reassembled ping payload.
    fake_stream.write.assert_awaited_once_with(ping_payload)


@pytest.mark.trio
async def test_ping_service_cancellation_propagates_cleanly():
    """
    Cancelling a ping() call (e.g. during host shutdown, or a caller-side
    timeout) must surface as trio.Cancelled, not as an UnboundLocalError
    from the `finally` block referencing an `event` that was never
    assigned because `except Exception` doesn't catch Cancelled.
    """
    from libp2p.host.ping import PingService

    class HangingStream:
        def __init__(self, metric_send_channel):
            self.metric_send_channel = metric_send_channel

        async def write(self, data):
            pass

        async def read(self, n):
            await trio.sleep_forever()

        async def close(self):
            pass

    class FakeHost:
        def __init__(self, stream):
            self._stream = stream

        async def new_stream(self, peer_id, protocols):
            return self._stream

    send_ch, _recv_ch = trio.open_memory_channel(10)
    svc = PingService(FakeHost(HangingStream(send_ch)))

    with trio.move_on_after(0.05) as scope:
        await svc.ping(object())

    assert scope.cancelled_caught


@pytest.mark.trio
async def test_handle_ping_closes_gracefully_on_idle_timeout(monkeypatch):
    """
    An idle timeout (no ping within RESP_TIMEOUT) is not a protocol
    error -- the responder should close() the stream, not reset() it.
    """
    from unittest.mock import AsyncMock

    import libp2p.host.ping as ping_mod

    monkeypatch.setattr(ping_mod, "RESP_TIMEOUT", 0.05)

    async def _hang(n: int) -> bytes:
        await trio.sleep_forever()
        return b""  # unreachable

    fake_stream = AsyncMock()
    fake_stream.read = AsyncMock(side_effect=_hang)
    fake_stream.muxed_conn.peer_id = "peer"

    await ping_mod.handle_ping(fake_stream)

    fake_stream.close.assert_awaited_once()
    fake_stream.reset.assert_not_called()

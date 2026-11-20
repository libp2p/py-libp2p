"""A completed fetch must not leave its provider-discovery task behind."""

from types import SimpleNamespace
from typing import Any

import pytest
import trio
from trio.testing import wait_all_tasks_blocked

from libp2p.bitswap.block_store import MemoryBlockStore
from libp2p.bitswap.cid import compute_cid_v1
from libp2p.bitswap.session import BitswapSession


@pytest.mark.trio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_successful_fetch_cancels_its_background_discovery(
    monkeypatch, autojump_clock, outcome
):
    entered, cancelled, finish, done = (trio.Event() for _ in range(4))
    calls = [0]

    async def discover(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return []
        entered.set()
        try:
            await trio.sleep_forever()
        finally:
            cancelled.set()

    client: Any = SimpleNamespace(
        host=SimpleNamespace(
            get_event_bus=lambda: SimpleNamespace(emit=lambda e: None)
        ),
        block_store=MemoryBlockStore(),
        provider_query_manager=SimpleNamespace(find_providers_single=discover),
        _started=True,
    )
    session = BitswapSession(client, 1)

    async def request(*args):
        await finish.wait()
        if outcome == "failure":
            raise OSError("fetch failed")
        return b"payload"

    monkeypatch.setattr(session, "_request_block", request)

    scope = trio.CancelScope()

    async def fetch():
        with scope:
            if outcome == "failure":
                with pytest.raises(OSError, match="fetch failed"):
                    await session.get_block(compute_cid_v1(b"payload"))
            else:
                assert await session.get_block(compute_cid_v1(b"payload")) == b"payload"
        done.set()

    async with trio.open_nursery() as nursery:
        client._nursery = nursery
        nursery.start_soon(fetch)
        await entered.wait()
        if outcome == "cancel":
            scope.cancel()
        else:
            finish.set()
        await done.wait()
        await wait_all_tasks_blocked()
        assert cancelled.is_set()
        assert not session._discovered_providers
        nursery.cancel_scope.cancel()

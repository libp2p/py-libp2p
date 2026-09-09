from typing import cast

import pytest
import trio

from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_connected_enqueues_and_adds_peer():
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        # Wait until peer is added via queue processing
        await p0.wait_for_peer(p1.my_id)
        assert p1.my_id in p0.peers


@pytest.mark.trio
async def test_disconnected_enqueues_and_removes_peer():
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        # Ensure present first
        await p0.wait_for_peer(p1.my_id)
        # Now disconnect and expect removal via dead peer queue
        await p0.host.get_network().close_peer(p1.host.get_id())
        # Wait for peer to be removed
        with trio.fail_after(1.0):
            while p1.my_id in p0.peers:
                await trio.sleep(0.01)
        assert p1.my_id not in p0.peers


@pytest.mark.trio
async def test_channel_closed_is_swallowed_in_notifee(monkeypatch) -> None:
    # Ensure PubsubNotifee catches BrokenResourceError from its send channel
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        # Find the PubsubNotifee registered on the network
        from libp2p.pubsub.pubsub_notifee import PubsubNotifee

        network = p0.host.get_network()
        notifees = getattr(network, "notifees", [])
        target = None
        for nf in notifees:
            if isinstance(nf, cast(type, PubsubNotifee)):
                target = nf
                break
        assert target is not None, "PubsubNotifee not found on network"

        async def failing_send(_peer_id):  # type: ignore[no-redef]
            raise trio.BrokenResourceError

        # Make initiator queue send fail; PubsubNotifee should swallow
        monkeypatch.setattr(target.initiator_peers_queue, "send", failing_send)

        # Connect peers; if exceptions are swallowed, service stays running
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        assert True


@pytest.mark.trio
async def test_duplicate_connection_does_not_duplicate_peer_state():
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        await p0.wait_for_peer(p1.my_id)
        # Connect again should not add duplicates
        await connect(p0.host, p1.host)
        await trio.sleep(0.1)
        assert list(p0.peers.keys()).count(p1.my_id) == 1


@pytest.mark.trio
async def test_blacklist_blocks_peer_added_by_notifee():
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        # Blacklist before connecting
        p0.add_to_blacklist(p1.my_id)
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        # Give handler a chance to run
        await trio.sleep(0.1)
        assert p1.my_id not in p0.peers

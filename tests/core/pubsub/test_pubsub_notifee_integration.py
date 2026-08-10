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


@pytest.mark.trio
async def test_ensure_peer_stream_registers_connected_peer():
    """
    The public recovery API registers an already-connected peer.

    This is the entry point for the one-shot registration race: when mDNS
    auto-connects peers before the muxer handshake completes, the first
    stream open fails and no second ``connected`` notifee ever fires. Apps
    call :meth:`Pubsub.ensure_peer_stream` after an explicit connect to
    (re)register the peer.
    """
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        assert await p0.ensure_peer_stream(p1.my_id)
        assert p1.my_id in p0.peers


@pytest.mark.trio
async def test_failed_stream_open_is_retried_until_peer_registered(monkeypatch):
    """
    A failed ``new_stream`` is retried, not silently dropped.

    Regression test for the race where the ``connected`` notifee fires before
    the muxer handshake completes: without the retry, the peer would never be
    registered and messages to it would be dropped forever.
    """
    from libp2p.network.exceptions import SwarmException

    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await p0.wait_until_ready()

        original_new_stream = p0.host.new_stream
        state = {"failures_left": 2}

        async def flaky_new_stream(peer_id, protocol_ids):
            if state["failures_left"] > 0:
                state["failures_left"] -= 1
                raise SwarmException("simulated pre-muxer-handshake failure")
            return await original_new_stream(peer_id, protocol_ids)

        monkeypatch.setattr(p0.host, "new_stream", flaky_new_stream)

        # Connect AFTER patching: the very first notifee-driven registration
        # attempts fail, exactly like the muxer-handshake race.
        await connect(p0.host, p1.host)

        # The background retry task must eventually register the peer despite
        # the initial failures (backoff: 0.5s + 1.0s before the 3rd attempt).
        await p0.wait_for_peer(p1.my_id, timeout=15.0)
        assert p1.my_id in p0.peers
        assert state["failures_left"] == 0


@pytest.mark.trio
async def test_ensure_peer_stream_fails_for_disconnected_peer():
    """
    ensure_peer_stream returns False without hanging when there is no
    connection (no stream can ever be opened).
    """
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await p0.wait_until_ready()
        # Never connect the peers; peer is not connected, so the retry loop
        # gives up immediately and the call returns False.
        assert not await p0.ensure_peer_stream(p1.my_id, timeout=2.0)
        assert p1.my_id not in p0.peers


@pytest.mark.trio
async def test_stream_failure_does_not_unregister_connected_peer():
    """
    A pubsub stream failure must not unregister a peer that is still
    connected.

    Regression test: the stream-failure path calls ``_handle_dead_peer``
    directly (skipping the dead-peer queue's active-connection guard). When
    multiple connections to the same peer exist — e.g. mDNS auto-connect
    racing an explicit dial — the stream can die on a broken connection while
    a healthy one remains; the peer must be re-registered instead of being
    silently dropped, or messaging with it dies forever.
    """
    async with PubsubFactory.create_batch_with_gossipsub(2) as (p0, p1):
        await connect(p0.host, p1.host)
        await p0.wait_until_ready()
        await p0.wait_for_peer(p1.my_id)
        assert p1.my_id in p0.peers

        # Simulate the stream dying while the connection is still alive
        # (exactly what the stream-failure path does).
        p0._handle_dead_peer(p1.my_id)
        assert p1.my_id not in p0.peers

        # Because the peer is still connected, pubsub must re-establish the
        # stream instead of leaving the peer unregistered.
        await p0.wait_for_peer(p1.my_id, timeout=10.0)
        assert p1.my_id in p0.peers

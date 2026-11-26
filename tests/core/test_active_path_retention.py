"""Retention regressions for the modules enabled by a long-running IPFS node."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from libp2p.kad_dht.routing_table import KBucket
from libp2p.network.auto_connector import AutoConnector
from libp2p.network.tag_store import TagStore
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.pubsub.gossipsub import GossipSub


def peer(i: int) -> ID:
    return ID(i.to_bytes(32, "big"))


def test_dial_diagnostics_have_a_fixed_capacity_and_expire():
    swarm: Any = SimpleNamespace()
    connector = AutoConnector(swarm)
    connector._max_tracking_peers = 32
    with patch("time.time", return_value=1000):
        for i in range(1000):
            connector._record_dial_outcome(peer(i), "failed")
    assert len(connector._dial_history) == 32
    assert peer(999) in connector._dial_history
    assert connector._stats["dialed"] == 0
    assert connector._stats["failed"] == 1000
    assert connector._stats["unique_dialed"] == 32
    with patch("time.time", return_value=10000):
        connector._prune_tracking_caches()
    assert not connector._dial_history
    assert connector._stats["unique_dialed"] == 0


@pytest.mark.trio
async def test_tracking_expires_even_while_above_connection_target():
    swarm: Any = SimpleNamespace(
        get_connected_peer_count=lambda: 50,
        get_total_connections=lambda: 50,
        connection_config=SimpleNamespace(
            min_connections=10, low_watermark=10, high_watermark=20
        ),
    )
    connector = AutoConnector(swarm)
    connector._started = True
    with patch("time.time", return_value=1000):
        connector._record_dial_outcome(peer(1), "ok")
        connector.record_disconnect(peer(1), lifespan=1)
    with patch("time.time", return_value=10000):
        await connector.maybe_connect()
    assert not connector._dial_history
    assert not connector._recent_disconnects
    assert not connector._quick_deaths
    assert not connector._quick_death_at


def test_disconnect_history_expires_without_erasing_live_quarantine():
    swarm: Any = SimpleNamespace()
    connector = AutoConnector(swarm)
    with patch("time.time", return_value=10000):
        for i in range(1000):
            connector.record_disconnect(peer(i), lifespan=60)
        assert not connector._quick_deaths
        connector.record_disconnect(peer(1001), lifespan=1)
        for _ in range(3):
            connector.record_disconnect(peer(1002), lifespan=1)
    with patch("time.time", return_value=10031):
        connector._prune_tracking_caches()
    assert peer(1002) in connector._quarantine_until
    with patch("time.time", return_value=12000):
        connector._prune_tracking_caches()
    assert not connector._recent_disconnects
    assert not connector._quick_deaths
    assert not connector._quick_death_at
    assert not connector._quarantine_until


def test_quick_disconnects_are_not_accumulated_across_expired_streaks():
    swarm: Any = SimpleNamespace()
    connector = AutoConnector(swarm)
    with patch("time.time", return_value=1000):
        connector.record_disconnect(peer(1), lifespan=1)
        connector.record_disconnect(peer(1), lifespan=1)
    with patch("time.time", return_value=3000):
        connector.record_disconnect(peer(1), lifespan=1)
    assert connector._quick_deaths[peer(1)] == 1
    assert not connector._quarantine_until


@pytest.mark.trio
async def test_removed_dht_peers_release_empty_tags():
    tags = TagStore()
    host: Any = SimpleNamespace(conn_manager=tags)
    bucket = KBucket(host, max_peers_per_subnet=0)
    for i in range(1000):
        pid = peer(i)
        assert await bucket.add_peer(PeerInfo(pid, []))
        assert bucket.remove_peer(pid)
    assert bucket.size() == 0
    assert tags.get_all_peers() == []


def test_tag_cleanup_preserves_connections_and_protection():
    tags = TagStore()
    pid = peer(1)
    tags.tag_peer(pid, "dht", 100)
    tags.record_connection(pid, 123)
    tags.untag_peer(pid, "dht")
    assert tags.get_tag_info(pid) is not None
    tags.remove_connection(pid, 123)
    assert tags.get_tag_info(pid) is None
    tags.tag_peer(pid, "dht", 100)
    tags.protect(pid, "application")
    tags.untag_peer(pid, "dht")
    assert tags.get_tag_info(pid) is not None
    assert tags.is_protected(pid)
    tags.unprotect(pid, "application")
    assert tags.get_tag_info(pid) is None


def test_backoff_expires_for_departed_peers_but_preserves_live_bans():
    router = GossipSub([], 6, 4, 12)
    with patch("time.time", return_value=10000):
        for i in range(1000):
            router._add_back_off(peer(i), "old-topic", False)
            router.remove_peer(peer(i))
        router._add_back_off(peer(2000), "live-topic", False, backoff_duration=500)
    with patch("time.time", return_value=10100):
        router._periodic_security_cleanup()
        assert "old-topic" not in router.back_off
        assert router._check_back_off(peer(2000), "live-topic")
    with patch("time.time", return_value=11000):
        assert not router._check_back_off(peer(2000), "live-topic")
    assert not router.back_off

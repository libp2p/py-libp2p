"""High-churn regressions for histories, waiters and optional resource APIs."""

from types import SimpleNamespace
from typing import Any

import pytest
import trio
from trio.testing import wait_all_tasks_blocked

from libp2p.peer.id import ID
from libp2p.peer.peerdata import PeerData
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub, ValidationCache, ValidationResult
from libp2p.rcmgr import Direction, ResourceManager
from libp2p.rcmgr.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimitScope,
    RateLimitStrategy,
)


def make_pubsub():
    host: Any = SimpleNamespace(
        get_network=lambda: SimpleNamespace(register_notifee=lambda *args: None),
        get_id=lambda: ID(b"local"),
        set_stream_handler=lambda *args: None,
    )
    router = GossipSub([], 6, 4, 12)
    return Pubsub(host, router, strict_signing=False), router


def waiter(kind):
    pubsub, router = make_pubsub()
    if kind == "peer":
        return pubsub._peer_added_events, lambda pid, timeout: pubsub.wait_for_peer(
            pid, timeout
        )
    if kind == "subscription":
        return (
            pubsub._subscription_events,
            lambda pid, timeout: pubsub.wait_for_subscription(pid, "topic", timeout),
        )
    return router._mesh_peer_events, lambda pid, timeout: router.wait_for_mesh(
        pid, "topic", timeout
    )


@pytest.mark.trio
@pytest.mark.parametrize("kind", ["peer", "subscription", "mesh"])
async def test_timed_out_waiters_release_registry_entries(kind):
    registry, wait = waiter(kind)
    for i in range(1000):
        with pytest.raises(trio.TooSlowError):
            await wait(ID(i.to_bytes(32, "big")), 0)
        assert not registry


@pytest.mark.trio
@pytest.mark.parametrize("kind", ["peer", "subscription", "mesh"])
async def test_one_cancelled_waiter_does_not_orphan_another(kind):
    registry, wait = waiter(kind)
    done = trio.Event()
    peer = ID(b"peer")

    async def remaining():
        await wait(peer, 5)
        done.set()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(remaining)
        await wait_all_tasks_blocked()
        event = next(iter(registry.values()))
        with trio.move_on_after(0) as scope:
            await wait(peer, 5)
        assert scope.cancelled_caught
        assert next(iter(registry.values())) is event
        event.set()
    assert done.is_set()
    assert not registry


def test_validation_overwrites_do_not_accumulate_lru_entries():
    cache = ValidationCache(max_size=4)
    for i in range(1000):
        cache.put(b"same", ValidationResult(True, float(i)))
    assert len(cache.cache) == len(cache.access_order) == 1


def test_protocol_updates_are_idempotent_and_keep_order():
    data = PeerData()
    for _ in range(1000):
        data.add_protocols(["/a", "/b", "/a"])
    assert data.get_protocols() == ["/a", "/b"]
    data.set_protocols(["/b", "/a", "/b"])
    assert data.get_protocols() == ["/b", "/a"]


@pytest.mark.parametrize(
    "strategy",
    [
        RateLimitStrategy.TOKEN_BUCKET,
        RateLimitStrategy.ADAPTIVE,
        RateLimitStrategy.FIXED_WINDOW,
        RateLimitStrategy.SLIDING_WINDOW,
    ],
)
def test_every_rate_strategy_bounds_entity_state(strategy):
    limiter = RateLimiter(
        RateLimitConfig(
            strategy=strategy,
            scope=RateLimitScope.PER_PEER,
            max_peers=4,
        )
    )
    for i in range(1000):
        limiter.try_allow(peer_id=ID(i.to_bytes(32, "big")), current_time=1000 + i)
    assert len(limiter._last_request_times) <= 4
    assert len(limiter._window_counts) <= 4
    assert len(limiter._token_buckets) <= 4


@pytest.mark.parametrize("limits", [(0, 1, 1), (1, 0, 1), (1, 1, 0)])
def test_entity_tracking_limits_must_be_positive(limits):
    with pytest.raises(ValueError, match="tracking limits"):
        RateLimitConfig(
            max_peers=limits[0], max_connections=limits[1], max_protocols=limits[2]
        )


def manager():
    return ResourceManager(
        enable_metrics=False,
        enable_connection_tracking=False,
        enable_rate_limiting=False,
        enable_circuit_breaker=False,
        enable_graceful_degradation=False,
    )


def test_scoped_resources_release_zero_counters_after_churn():
    rm = manager()
    rm.set_service_stream_limit("service", 2)
    rm.set_service_peer_stream_limit("service", 2)
    rm.set_protocol_stream_limit("protocol", 2)
    rm.set_protocol_peer_stream_limit("protocol", 2)
    for i in range(1000):
        assert rm.acquire_scoped_stream(
            str(i), Direction.OUTBOUND, "service", "protocol"
        )
        rm.release_scoped_stream(str(i), Direction.OUTBOUND, "service", "protocol")
    assert not rm._service_stream_counts
    assert not rm._service_peer_stream_counts
    assert not rm._protocol_stream_counts
    assert not rm._protocol_peer_stream_counts
    assert rm._current_streams == 0


@pytest.mark.parametrize(
    "denied_scope", ["service", "service-peer", "protocol", "protocol-peer"]
)
def test_failed_scoped_acquisition_rolls_back_without_zero_entries(denied_scope):
    rm = manager()
    rm.set_service_stream_limit("service", 0 if denied_scope == "service" else 2)
    rm.set_service_peer_stream_limit(
        "service", 0 if denied_scope == "service-peer" else 2
    )
    rm.set_protocol_stream_limit("protocol", 0 if denied_scope == "protocol" else 2)
    rm.set_protocol_peer_stream_limit(
        "protocol", 0 if denied_scope == "protocol-peer" else 2
    )
    assert not rm.acquire_scoped_stream(
        "peer", Direction.OUTBOUND, "service", "protocol"
    )
    assert not rm._service_stream_counts
    assert not rm._service_peer_stream_counts
    assert not rm._protocol_stream_counts
    assert not rm._protocol_peer_stream_counts
    assert rm._current_streams == 0


def test_releasing_one_scope_preserves_another_active_owner():
    rm = manager()
    rm.set_service_stream_limit("service", 2)
    rm.set_service_peer_stream_limit("service", 2)
    rm.set_protocol_stream_limit("protocol", 2)
    rm.set_protocol_peer_stream_limit("protocol", 2)
    for peer in ["one", "two"]:
        assert rm.acquire_scoped_stream(peer, Direction.OUTBOUND, "service", "protocol")
    rm.release_scoped_stream("one", Direction.OUTBOUND, "service", "protocol")
    assert rm._service_stream_counts == {"service": 1}
    assert rm._service_peer_stream_counts == {("service", "two"): 1}
    assert rm._protocol_stream_counts == {"protocol": 1}
    assert rm._protocol_peer_stream_counts == {("protocol", "two"): 1}
    rm.release_scoped_stream("two", Direction.OUTBOUND, "service", "protocol")
    assert rm._current_streams == 0


def test_scorer_ip_changes_release_old_subnet_membership():
    from libp2p.pubsub.score import PeerScorer, ScoreParams

    scorer = PeerScorer(ScoreParams())
    peer = ID(b"moving")
    survivor = ID(b"staying")
    scorer.add_peer_ip(survivor, "10.0.0.2")
    for i in range(1000):
        scorer.add_peer_ip(peer, f"10.{i // 256}.{i % 256}.1")
    scorer.remove_peer(peer)
    assert scorer.peer_ips == {"10.0.0.2": {survivor}}
    assert scorer.subnet_tracking == {"10.0.0": {survivor}}
    scorer.remove_peer(survivor)
    assert not scorer.subnet_tracking


@pytest.mark.trio
@pytest.mark.parametrize("outcome", ["error", "cancel"])
async def test_have_probe_setup_failure_releases_want(monkeypatch, outcome):
    from libp2p.bitswap.cid import compute_cid_v1
    from libp2p.bitswap.client import BitswapClient

    host: Any = SimpleNamespace(
        get_event_bus=lambda: SimpleNamespace(emit=lambda event: None),
        get_network=lambda: SimpleNamespace(connections={}),
        set_stream_handler=lambda *args: None,
    )
    client = BitswapClient(host)
    cid = compute_cid_v1(b"probe")

    async def send(*args):
        if outcome == "error":
            raise RuntimeError("setup failed")
        await trio.lowlevel.checkpoint()

    monkeypatch.setattr(client, "_send_wantlist_to_peer", send)
    if outcome == "error":
        with pytest.raises(RuntimeError, match="setup failed"):
            await client.have_block(cid, ID(b"remote"))
    else:
        with trio.CancelScope() as scope:
            scope.cancel()
            await client.have_block(cid, ID(b"remote"))
    assert not client._wantlist
    assert not client._broadcast_wants


@pytest.mark.trio
async def test_cancel_want_releases_pending_peer_statistics():
    from libp2p.bitswap.cid import compute_cid_v1, parse_cid
    from libp2p.bitswap.client import BitswapClient

    host: Any = SimpleNamespace(
        get_event_bus=lambda: SimpleNamespace(emit=lambda event: None),
        get_network=lambda: SimpleNamespace(connections={}),
        set_stream_handler=lambda *args: None,
    )
    client = BitswapClient(host)
    peer = ID(b"remote")
    other = parse_cid(compute_cid_v1(b"still active"))
    client.peer_manager.record_request(peer, other)
    for i in range(1000):
        cid = parse_cid(compute_cid_v1(str(i).encode()))
        await client.want_block(cid)
        client.peer_manager.record_request(peer, cid)
        await client.cancel_want(cid)
    stats = client.peer_manager.peers[peer]
    assert set(stats._pending_requests) == {other}
    assert stats.requests_sent == 1001
    assert stats.timeouts == 0


@pytest.mark.parametrize("subscribers", [False, True])
def test_expired_fanout_releases_topic_and_publish_time(subscribers):
    import time

    pubsub, router = make_pubsub()
    for i in range(1000):
        topic = str(i)
        router.fanout[topic] = set()
        router.time_since_last_publish[topic] = int(time.time()) - 10000
        if subscribers:
            pubsub.peer_topics[topic] = set()
    router.fanout_heartbeat()
    assert not router.fanout
    assert not router.time_since_last_publish


def test_delivery_health_releases_expired_topic_keys():
    _, router = make_pubsub()
    for i in range(1000):
        router.recent_message_deliveries[str(i)] = [0.0]
    router._calculate_message_delivery_health()
    assert not router.recent_message_deliveries


@pytest.mark.parametrize("mode", ["remove", "expire", "evict"])
def test_value_removal_releases_republish_metadata(monkeypatch, mode):
    from libp2p.kad_dht.pb.kademlia_pb2 import Record
    from libp2p.kad_dht.value_store import ValueStore

    host: Any = SimpleNamespace()
    store = ValueStore(host, ID(b"local"))
    monkeypatch.setattr("libp2p.kad_dht.value_store.MAX_VALUE_STORE_SIZE", 1)
    for i in range(1000):
        key = str(i).encode()
        store.store[key] = (Record(key=key), 0.0)
        store.local_keys.add(key)
        store._last_republish[key] = 1.0
        if mode == "remove":
            store.remove(key)
        elif mode == "expire":
            store.cleanup_expired()
        else:
            store._evict_if_full()
    assert not store.store
    assert not store.local_keys
    assert not store._last_republish


@pytest.mark.parametrize("adaptive", [False, True])
def test_heartbeat_expires_histories_without_mesh_topics(adaptive):
    import time

    _, router = make_pubsub()
    router.adaptive_gossip_enabled = adaptive
    now = time.time()
    router.recent_peer_connections[:] = [0.0] * 1000 + [now]
    router.recent_peer_disconnections[:] = [0.0] * 1000 + [now]
    router.recent_message_deliveries["gone"] = [0.0] * 1000
    router.time_since_last_publish["gone"] = 0
    router._periodic_security_cleanup()
    assert router.recent_peer_connections == [now]
    assert router.recent_peer_disconnections == [now]
    assert not router.recent_message_deliveries
    assert not router.time_since_last_publish


@pytest.mark.trio
async def test_republish_finishing_after_removal_does_not_retain_timestamp():
    from libp2p.kad_dht.pb.kademlia_pb2 import Record
    from libp2p.kad_dht.value_store import ValueStore

    host: Any = SimpleNamespace(
        get_event_bus=lambda: SimpleNamespace(emit=lambda event: None)
    )
    store = ValueStore(host, ID(b"local"))
    store.store[b"key"] = (Record(key=b"key"), 0.0)
    store.local_keys.add(b"key")

    async def lookup(key):
        store.remove(key)
        await trio.lowlevel.checkpoint()
        return []

    await store._republish_records(SimpleNamespace(find_closest_peers_network=lookup))
    assert not store._last_republish

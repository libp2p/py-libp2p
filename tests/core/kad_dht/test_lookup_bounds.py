"""
Iterative lookups must terminate even against a peer that keeps supplying new
closer peers.

get_value() and find_providers() used to schedule every closer peer returned by
every response with no total deadline and no cap on peers contacted, so a
response stream of fresh peer IDs kept the lookup (and its candidate, queried
and result sets) alive indefinitely.
"""

import hashlib

import pytest
import trio

from libp2p.kad_dht.common import ALPHA, MAX_LOOKUP_QUERIES
from libp2p.kad_dht.kad_dht import KadDHT
from libp2p.kad_dht.provider_store import ProviderStore
from libp2p.peer.id import ID


def _peer_id(n: int) -> ID:
    return ID(b"\x12\x20" + hashlib.sha256(n.to_bytes(8, "big")).digest())


class _EventBus:
    def emit(self, event: object) -> None:
        pass


class _PeerStore:
    def addrs(self, peer_id: ID) -> list[object]:
        return []

    def add_addrs(self, peer_id: ID, addrs: object, ttl: int = 0) -> None:
        pass


class _Host:
    def get_id(self) -> ID:
        return _peer_id(0)

    def get_peerstore(self) -> _PeerStore:
        return _PeerStore()

    def get_event_bus(self) -> _EventBus:
        return _EventBus()


class _Validator:
    def validate(self, key: str, value: bytes) -> None:
        pass

    def select(self, key: str, values: list[bytes]) -> int:
        return 0


class _Routing:
    async def find_closest_peers_network(
        self, target_key: bytes, count: int = 20
    ) -> list[ID]:
        return [_peer_id(i) for i in range(1, 11)]


class _EndlessValueStore:
    """Returns no record but a batch of fresh closer peers on every query."""

    calls: int

    def __init__(self) -> None:
        self.calls = 0

    def get(self, key: bytes) -> None:
        return None

    async def _get_from_peer(self, peer_id: ID, key: bytes, **kwargs: object):
        self.calls += 1
        await trio.sleep(0)
        base = 1000 + self.calls * 20
        return None, [_peer_id(base + i) for i in range(20)]


@pytest.mark.trio
async def test_get_value_lookup_stops_at_query_cap() -> None:
    dht = KadDHT.__new__(KadDHT)
    dht.host = _Host()  # type: ignore[assignment]
    dht.local_peer_id = _peer_id(0)
    dht.validator = _Validator()  # type: ignore[assignment]
    store = _EndlessValueStore()
    dht.value_store = store  # type: ignore[assignment]
    dht.peer_routing = _Routing()  # type: ignore[assignment]

    with trio.fail_after(20.0):
        result = await dht.get_value("/test/key")

    assert result is None
    # A little slack for the ALPHA queries already in flight at the cap.
    assert store.calls <= MAX_LOOKUP_QUERIES + ALPHA


@pytest.mark.trio
async def test_provider_lookup_stops_at_query_cap() -> None:
    store = ProviderStore(host=_Host())  # type: ignore[arg-type]
    store.peer_routing = _Routing()
    calls = 0

    async def endless(peer_id: ID, key: bytes):
        nonlocal calls
        calls = calls + 1
        await trio.sleep(0)
        base = 50000 + calls * 20
        return [], [_peer_id(base + i) for i in range(20)]

    store._get_providers_from_peer_with_closers = endless  # type: ignore[method-assign]

    with trio.fail_after(20.0):
        providers = await store.find_providers(b"\x12\x20" + b"k" * 32, count=20)

    assert providers == []
    assert calls <= MAX_LOOKUP_QUERIES + ALPHA


@pytest.mark.trio
async def test_get_value_stops_at_deadline(monkeypatch) -> None:
    """The lookup also terminates on wall-clock time, not just query count."""
    import libp2p.kad_dht.kad_dht as kad_module

    monkeypatch.setattr(kad_module, "MAX_LOOKUP_DURATION", 0.05)

    class SlowStore(_EndlessValueStore):
        async def _get_from_peer(
            self, peer_id: ID, key: bytes, **kwargs: object
        ) -> tuple[None, list[ID]]:
            self.calls += 1
            await trio.sleep(0.01)
            return None, [_peer_id(90000 + self.calls)]

    dht = KadDHT.__new__(KadDHT)
    dht.host = _Host()  # type: ignore[assignment]
    dht.local_peer_id = _peer_id(0)
    dht.validator = _Validator()  # type: ignore[assignment]
    store = SlowStore()
    dht.value_store = store  # type: ignore[assignment]
    dht.peer_routing = _Routing()  # type: ignore[assignment]

    with trio.fail_after(5.0):
        await dht.get_value("/test/key")

    assert 0 < store.calls < 100

"""
Tests for the iterative lookup engine in ``libp2p.kad_dht.lookup``.

A simulated network stands in for FIND_NODE: ``query(peer)`` answers from that
peer's own view, so the engine runs exactly as ``find_closest_peers_network``
drives it, without sockets.
"""

import random

import pytest

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.kad_dht.common import BETA
from libp2p.kad_dht.lookup import Lookup
from libp2p.kad_dht.utils import sort_peer_ids_by_distance
from libp2p.peer.id import ID

TARGET = b"lookup-target"


def _peers(n: int) -> list[ID]:
    return [ID.from_pubkey(create_new_key_pair().public_key) for _ in range(n)]


@pytest.mark.trio
async def test_collect_adds_unseen_answers_once() -> None:
    a, b, c = _peers(3)

    async def query(peer: ID) -> list[ID]:
        return [a, b, a]

    lookup = Lookup(TARGET, [c], query, local_id=c)
    new_peers = [a]
    await lookup._collect(c, new_peers)
    assert new_peers == [a, b]


@pytest.mark.trio
async def test_collect_treats_a_failed_query_as_empty() -> None:
    (a,) = _peers(1)

    async def query(peer: ID) -> list[ID]:
        raise RuntimeError("query failed")

    lookup = Lookup(TARGET, [a], query, local_id=a)
    new_peers: list[ID] = []
    await lookup._collect(a, new_peers)
    assert new_peers == []


@pytest.mark.trio
async def test_no_start_peers_returns_empty() -> None:
    (me,) = _peers(1)

    async def query(peer: ID) -> list[ID]:  # pragma: no cover - never called
        raise AssertionError

    assert await Lookup(TARGET, [], query, local_id=me).run() == []


@pytest.mark.trio
async def test_converges_and_queries_the_beta_closest() -> None:
    """
    Each peer knows a random 8 others and answers with the 20 of those closest
    to the target. Starting from a few far peers, the lookup must reach the
    true closest peers and contact the BETA closest before it returns.
    """
    me, *net = _peers(60)
    rnd = random.Random(1384)
    view = {p: rnd.sample([q for q in net if q != p], 8) for p in net}
    truth = sort_peer_ids_by_distance(TARGET, net)
    # Every peer must be reachable from the start set for "true closest" to hold.
    for p in truth[:5]:
        view[truth[-1]].append(p)

    async def query(peer: ID) -> list[ID]:
        return sort_peer_ids_by_distance(TARGET, view[peer])[:20]

    start = truth[-3:]  # the three farthest peers
    lookup = Lookup(TARGET, list(start), query, local_id=me, rng=random.Random(7))
    result = await lookup.run()

    assert result[0] == truth[0]
    assert set(truth[:BETA]) <= lookup.queried_peers
    assert me not in lookup.queried_peers
    assert lookup.rounds >= 2


@pytest.mark.trio
async def test_same_seed_same_queries() -> None:
    """The draw comes only from ``rng``, so a seeded run is reproducible."""
    me, *net = _peers(40)
    rnd = random.Random(42)
    view = {p: rnd.sample([q for q in net if q != p], 10) for p in net}

    async def query(peer: ID) -> list[ID]:
        return sort_peer_ids_by_distance(TARGET, view[peer])[:20]

    runs = []
    for _ in range(2):
        lookup = Lookup(TARGET, net[:5], query, local_id=me, rng=random.Random(9))
        runs.append((await lookup.run(), lookup.queried_peers, lookup.rounds))
    assert runs[0] == runs[1]

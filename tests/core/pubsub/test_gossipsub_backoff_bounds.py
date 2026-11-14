"""Regression coverage for remote-controlled GossipSub PRUNE backoff state."""

import time

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID,
    GossipSub,
)
from tests.utils.factories import IDFactory

# Public assertion targets for the bounds enforced by gossipsub.py.
_MAX_BACKOFF_SECONDS = 24 * 60 * 60
_MAX_BACKOFF_TOPICS = 10_000


def _new_gossipsub() -> GossipSub:
    return GossipSub(
        protocols=[PROTOCOL_ID],
        degree=6,
        degree_low=4,
        degree_high=12,
    )


def test_remote_backoff_duration_is_clamped():
    """A peer cannot pin a topic until the far future with PRUNE.backoff."""
    router = _new_gossipsub()
    peer = IDFactory()
    before = int(time.time())

    router._add_back_off(peer, "attacker-topic", False, 10**18)

    assert router.back_off["attacker-topic"][peer] <= before + _MAX_BACKOFF_SECONDS


def test_backoff_topic_count_is_bounded():
    """Unique topic IDs must not grow the backoff map without limit."""
    router = _new_gossipsub()
    peer = IDFactory()

    for i in range(_MAX_BACKOFF_TOPICS + 100):
        router._add_back_off(peer, f"topic-{i}", False, _MAX_BACKOFF_SECONDS)

    assert len(router.back_off) == _MAX_BACKOFF_TOPICS
